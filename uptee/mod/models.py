import mimetypes
import os
import psutil
import signal
from django.db import models
from django.contrib.auth.models import User
from django.forms import ValidationError
from mod.tasks import run_server
from settings import MEDIA_ROOT
from shutil import rmtree
from lib.twconfig import Config as TwConfig
from lib.twserverinfo import ServerInfo


class FreePortManager(models.Manager):
    def get_query_set(self):
        return super(FreePortManager, self).get_query_set().filter(is_active=False)


class Mod(models.Model):
    mod_file = models.FileField(upload_to='uploads', help_text='Should be .zip or .tar')
    upload_date = models.DateTimeField('Uploaddatum', auto_now=True)
    title = models.CharField(blank=False, max_length=100)
    mimetype = models.CharField(editable=False, max_length=100)

    class Meta:
        ordering = ['upload_date', 'title']

    def __unicode__(self):
        return self.title

    def save(self):
        self.mimetype = mimetypes.guess_type(self.mod_file.path)[0]
        super(Mod, self).save()

    def delete(self):
        if os.path.exists(self.mod_file.path):
            os.remove(self.mod_file.path)
        path = os.path.join(MEDIA_ROOT, 'mods', self.title)
        if os.path.exists(path):
            rmtree(path)
        super(Mod, self).delete()


class Port(models.Model):
    port = models.IntegerField(unique=True)
    is_active = models.BooleanField(default=False)

    objects = models.Manager()
    free = FreePortManager()

    @staticmethod
    def get_free_port():
        try:
            return Port.free.all()[0]
        except:
            return None

    class Meta:
        ordering = ['port']

    def __unicode__(self):
        return str(self.port)

    def validate_unique(self, exclude=None):
        if self.port < 0 or self.port > 65535:
            raise ValidationError('The used Port is out of range.')
        super(Port, self).validate_unique(exclude=exclude)

    def save(self):
        self.full_clean()
        super(Port, self).save()


class Server(models.Model):
    owner = models.ForeignKey(User, related_name='servers')
    mod = models.ForeignKey(Mod, related_name='servers')
    pid = models.IntegerField(blank=True, null=True, unique=True)
    port = models.OneToOneField(Port, blank=True, null=True, related_name='server')
    is_active = models.BooleanField(default=False)
    online = models.BooleanField(default=False)

    @property
    def is_online(self):
        if self.port and self.port.is_active and self.online:
            return True
        return False

    @property
    def info(self):
        if self.is_online and self.check_online():
            s = ServerInfo()
            s.send(self.port.port)
            return s
        return None

    @property
    def map_exists(self):
        if self.is_online:  # return true if server is online
            return True
        map_name = self.config_options.get(command='sv_map').value
        if self.maps.filter(name=map_name):
            return True
        return False

    class Meta:
        ordering = ['owner', 'mod', 'port']

    def __unicode__(self):
        return '{0} ({1}) Owner: {2}'.format(self.mod.title, self.is_online, self.owner.username)

    def check_online(self):
        if self.pid in psutil.get_pid_list():
            if not self.online:
                self.online = True
                self.save()
            return True
        self.set_offline()
        return False

    def set_offline(self):
        if self.port and self.port.is_active:
            self.port.is_active = False
            self.port.save()
            self.port = None
        if self.pid in psutil.get_pid_list():
            os.kill(self.pid, signal.SIGTERM)
        self.pid = None
        self.online = False
        self.save()

    def set_online(self):
        ports = Port.objects.filter(server=self)
        if ports:
            for port in ports:
                server = port.server
                server.set_offline()
        self.port = Port.get_free_port()
        self.port.is_active = True
        self.port.save()
        path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title)
        config = TwConfig(os.path.join(path, 'generated.cfg'))
        for option in self.config_options.all():
            config.add_option(option.command, option.value, option.get_widget_display())
        config.add_option('sv_port', self.port.port)
        for tune in self.config_tunes.all():
            config.add_tune(tune.command, tune.value)
        for vote in self.config_votes.all():
            config.add_vote(vote.command, vote.title)
        config.write()
        with open(os.path.join(path, 'storage.cfg'), 'w') as storage:
            storage.write('add_path servers/{0}/{1}\nadd_path $CURRENTDIR\n'.format(self.owner.username, self.id))
        run_server.delay(path, self)

    def delete(self):
        self.set_offline()
        path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'servers', self.owner.username)
        if os.path.exists(path):
            rmtree(path)
        super(Server, self).delete()


class Config(models.Model):
    server = models.ForeignKey(Server, related_name='config_%(class)ss')
    command = models.CharField(max_length=100)

    class Meta:
        abstract = True


class Option(Config):
    value = models.CharField(blank=True, max_length=500)

    WIDGET_TEXT = 1
    WIDGET_TEXTAREA = 2
    WIDGET_PASSWORD = 3
    WIDGET_CHECKBOX = 4
    WIDGET_CHOICES = (
        (WIDGET_TEXT, 'text'),
        (WIDGET_TEXTAREA, 'textarea'),
        (WIDGET_PASSWORD, 'password'),
        (WIDGET_CHECKBOX, 'checkbox'),
    )
    widget = models.IntegerField(choices=WIDGET_CHOICES, default=WIDGET_TEXT)

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Tune(Config):
    value = models.FloatField()

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Vote(Config):
    title = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Map(models.Model):
    server = models.ForeignKey(Server, related_name="maps")
    name = models.CharField(max_length=100)
    author = models.CharField(max_length=100, blank=True)
    info = models.CharField(max_length=300, blank=True)
    download_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['name']

    def get_download_url(self):
        path = os.path.join(MEDIA_ROOT, 'mods', self.server.mod.title, 'servers', self.server.owner.username, '{0}'.format(self.server.id), 'maps')
        if os.path.exists(path):
            for _file in os.listdir(path):
                if os.path.splitext(_file)[0] == self.name and os.path.splitext(_file)[1].lower() == '.map':
                    return os.path.join(path, _file)
        return None

    def delete(self):
        path = self.get_download_url()
        if path:
            os.remove(path)
        super(Map, self).delete()
