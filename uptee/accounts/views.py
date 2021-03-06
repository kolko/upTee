from captcha.conf import settings as captcha_settings
from captcha.models import CaptchaStore
from django.core.mail import mail_admins
from django.contrib.auth import logout as user_logout
from django.contrib.auth import login as user_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.shortcuts import redirect, render_to_response
from django.template import RequestContext
from accounts.forms import *
from settings import ADMINS, DEBUG


@login_required
def logout(request):
    user_logout(request)
    messages.success(request, "Successfully logged out.")
    return redirect(request.REQUEST.get('next', reverse('home')))


def login(request):
    if request.user.is_authenticated() or request.method != 'POST':
        return redirect(reverse('home'))
    post = request.POST.copy()
    next = post.get('next', reverse('home'))
    form = AuthenticationForm(data=post)
    if form.is_valid():
        user_login(request, form.get_user())
        messages.success(request, "Successfully logged in.")
    else:
        messages.warning(request, "The combination of username and password is wrong or your account is not activated yet.")
    if next == reverse('logout') or next == reverse('logout')[:-1]:
        next = reverse('home')
    return redirect(next)


@login_required
def settings(request):
    form = SettingsUserForm(instance=request.user)
    if request.method == 'POST':
        form = SettingsUserForm(request.POST,
            instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was saved successfully")
    return render_to_response('accounts/settings.html', {
            'form': form,
        }, context_instance=RequestContext(request))


@login_required
def change_password(request):
    form = PasswordChangeForm(current_user=request.user)
    if request.method == 'POST':
        form = PasswordChangeForm(request.POST, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, u'Password changed successfully.')
    return render_to_response('accounts/password_change.html', {
            'form': form,
        }, context_instance=RequestContext(request))


def register(request):
    if request.user.is_authenticated():
        return redirect(reverse('home'))
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            new_user = User(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=make_password(form.cleaned_data['password1']),
                is_active=False,
            )
            new_user.save()
            messages.success(request, "Your account was successfully created. An Admin will contact you shortly.")
            if ADMINS:
                mail_admins('User registration', u'The following user just registered and wants to be activated:\r\n\r\n{0}'.format(form.cleaned_data['username']), fail_silently=not DEBUG)
            return redirect(reverse('home'))
    else:
        form = RegisterForm()
    challenge, response = captcha_settings.get_challenge()()
    store = CaptchaStore.objects.create(challenge=challenge, response=response)
    key = store.hashkey
    return render_to_response('accounts/register.html', {
            'captcha': key,
            'register_form': form,
        }, context_instance=RequestContext(request))
