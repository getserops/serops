"""Set the email domains that route SSO sign-ins to an organisation.

On an install with several organisations a domain decides which
organisation's identity provider a newcomer is sent to, so platform
operators set them here (organisation admins of a single-organisation
install can also set them in Settings → Security).

    python manage.py sso_domains "Acme" acme.com acme.io
    python manage.py sso_domains 4 --clear
    python manage.py sso_domains --list
"""
from django.core.management.base import BaseCommand, CommandError

from Organisations.models import Organisations
from Users.models import SecuritySettings
from Users.sso_roles import normalise_domains


class Command(BaseCommand):
    help = "Set or list the SSO email domains of an organisation"

    def add_arguments(self, parser):
        parser.add_argument('organisation', nargs='?', help='Organisation id or exact name')
        parser.add_argument('domains', nargs='*')
        parser.add_argument('--clear', action='store_true', help='Remove every domain')
        parser.add_argument('--list', action='store_true', help='List the domains of every organisation')

    def handle(self, *args, **opts):
        if opts['list']:
            for sec in SecuritySettings.objects.select_related('organisation').exclude(sso_domains=[]):
                self.stdout.write(f"{sec.organisation_id}\t{sec.organisation.name}\t{', '.join(sec.sso_domains)}")
            return
        ref = opts['organisation']
        if not ref:
            raise CommandError('Name an organisation (id or name), or use --list')
        org = (Organisations.objects.filter(pk=int(ref)).first() if ref.isdigit()
               else Organisations.objects.filter(name=ref).first())
        if org is None:
            raise CommandError(f'No organisation {ref!r}')
        if opts['clear'] == bool(opts['domains']):
            raise CommandError('Give domains, or --clear')
        try:
            domains = [] if opts['clear'] else normalise_domains(opts['domains'])
        except ValueError as e:
            raise CommandError(str(e))
        sec, _ = SecuritySettings.objects.get_or_create(organisation=org)
        taken = sorted({d for other in SecuritySettings.objects.exclude(pk=sec.pk)
                        for d in domains if d in (other.sso_domains or [])})
        if taken:
            raise CommandError(f'Already used by another organisation: {", ".join(taken)}')
        sec.sso_domains = domains
        sec.save(update_fields=['sso_domains', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(f"{org.name}: {', '.join(domains) or 'no domains'}"))
