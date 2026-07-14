"""
Management command to check for expiring contracts and send email alerts.
Run this command daily via cron job or task scheduler.
"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import date, timedelta
from hr.staff.models import StaffContract


class Command(BaseCommand):
    help = 'Check for expiring contracts and send email alerts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Perform a dry run without sending emails or updating records',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No emails will be sent'))
        
        # Get all active contracts with end dates
        active_contracts = StaffContract.objects.filter(
            status='ACTIVE',
            end_date__isnull=False
        )
        
        today = date.today()
        alerts_sent = 0
        
        for contract in active_contracts:
            days_until_expiry = (contract.end_date - today).days
            
            # Check for 90-day alert
            if 85 <= days_until_expiry <= 90 and not contract.alert_sent_90_days:
                self.send_expiry_alert(contract, 90, dry_run)
                if not dry_run:
                    contract.alert_sent_90_days = True
                    contract.save()
                alerts_sent += 1
            
            # Check for 60-day alert
            elif 55 <= days_until_expiry <= 60 and not contract.alert_sent_60_days:
                self.send_expiry_alert(contract, 60, dry_run)
                if not dry_run:
                    contract.alert_sent_60_days = True
                    contract.save()
                alerts_sent += 1
            
            # Check for 30-day alert
            elif 25 <= days_until_expiry <= 30 and not contract.alert_sent_30_days:
                self.send_expiry_alert(contract, 30, dry_run)
                if not dry_run:
                    contract.alert_sent_30_days = True
                    contract.save()
                alerts_sent += 1
            
            # Check for expired contracts
            elif days_until_expiry < 0 and contract.status == 'ACTIVE':
                self.stdout.write(
                    self.style.ERROR(
                        f'Contract {contract.contract_number} has EXPIRED '
                        f'({abs(days_until_expiry)} days ago)'
                    )
                )
                if not dry_run:
                    # Optionally update status to EXPIRED
                    # contract.status = 'EXPIRED'
                    # contract.save()
                    pass
        
        if alerts_sent > 0:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully sent {alerts_sent} expiry alerts')
            )
        else:
            self.stdout.write(self.style.SUCCESS('No alerts to send at this time'))
        
        # Summary statistics
        total_active = active_contracts.count()
        expiring_90 = len([c for c in active_contracts if 0 <= (c.end_date - today).days <= 90])
        expiring_30 = len([c for c in active_contracts if 0 <= (c.end_date - today).days <= 30])
        expired = len([c for c in active_contracts if (c.end_date - today).days < 0])
        
        self.stdout.write(f'\nContract Summary:')
        self.stdout.write(f'  Total Active Contracts: {total_active}')
        self.stdout.write(f'  Expiring within 90 days: {expiring_90}')
        self.stdout.write(f'  Expiring within 30 days: {expiring_30}')
        self.stdout.write(f'  Expired (not updated): {expired}')

    def send_expiry_alert(self, contract, days_notice, dry_run=False):
        """Send email alert for expiring contract."""
        subject = f'Contract Expiry Alert - {days_notice} Days Notice'
        
        message = f"""
Dear HR Team,

This is an automated reminder that the following contract is expiring in approximately {days_notice} days:

Contract Details:
- Contract Number: {contract.contract_number}
- Staff Member: {contract.staff.full_name} ({contract.staff.staff_no})
- Position: {contract.position}
- Department: {contract.department.name}
- Contract Type: {contract.get_contract_type_display()}
- Start Date: {contract.start_date.strftime('%B %d, %Y')}
- End Date: {contract.end_date.strftime('%B %d, %Y')}
- Days Until Expiry: {contract.days_until_expiry}

Action Required:
Please review this contract and take appropriate action (renewal, termination, or other).

Access the contract details in the HRMS:
[Log in to HRMS and navigate to Contracts section]

---
This is an automated message from the NDUHR System.
        """
        
        # HR admin email (configure in settings)
        recipient_list = [
            getattr(settings, 'HR_ADMIN_EMAIL', 'hro@ndejjeuniversity.ac.ug')
        ]
        
        # Also send to staff's email if available
        if contract.staff.university_email:
            recipient_list.append(contract.staff.university_email)
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would send {days_notice}-day alert for '
                    f'{contract.contract_number} ({contract.staff.full_name}) '
                    f'to {", ".join(recipient_list)}'
                )
            )
        else:
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Sent {days_notice}-day alert for {contract.contract_number} '
                        f'({contract.staff.full_name})'
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Failed to send email for {contract.contract_number}: {str(e)}'
                    )
                )
