"""
Monthly Leave Accrual Command
Run this at end of each month to accrue leave for all active staff
Usage: python manage.py run_monthly_accrual
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
from datetime import date
from calendar import monthrange

from hr.leave.models import LeaveBalance, LeaveType, LeavePolicy, LeaveAccrual
from hr.staff.models import StaffProfile


class Command(BaseCommand):
    help = 'Run monthly leave accrual for all active staff'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=int,
            help='Month number (1-12). Defaults to last month.',
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Year. Defaults to current year.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate accrual without saving to database',
        )

    def handle(self, *args, **options):
        # Determine accrual month and year
        if options['month'] and options['year']:
            accrual_month = options['month']
            accrual_year = options['year']
        else:
            today = timezone.now().date()
            # Last month
            if today.month == 1:
                accrual_month = 12
                accrual_year = today.year - 1
            else:
                accrual_month = today.month - 1
                accrual_year = today.year
        
        # Last day of accrual month
        last_day = monthrange(accrual_year, accrual_month)[1]
        accrual_date = date(accrual_year, accrual_month, last_day)
        
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.SUCCESS(
            f'Running Monthly Leave Accrual for {accrual_date.strftime("%B %Y")}'
        ))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be saved'))
        
        # Get all active staff
        active_staff = StaffProfile.objects.filter(is_active=True)
        
        total_staff = active_staff.count()
        processed = 0
        errors = 0
        
        self.stdout.write(f'Processing {total_staff} active staff members...\n')
        
        for staff in active_staff:
            try:
                self._process_staff_accrual(staff, accrual_date, accrual_year, dry_run)
                processed += 1
                
                if processed % 10 == 0:
                    self.stdout.write(f'Processed {processed}/{total_staff}...')
            
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(
                    f'Error processing {staff.full_name} ({staff.staff_no}): {str(e)}'
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nAccrual Complete:'
        ))
        self.stdout.write(f'  - Staff Processed: {processed}/{total_staff}')
        self.stdout.write(f'  - Errors: {errors}')
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Accruals saved to database for {accrual_date.strftime("%B %Y")}'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'DRY RUN - No changes saved. Run without --dry-run to apply.'
            ))

    def _process_staff_accrual(self, staff, accrual_date, accrual_year, dry_run):
        """Process accrual for a single staff member"""
        
        # Get applicable leave types with accrual
        leave_types = LeaveType.objects.filter(is_active=True, has_accrual=True)
        
        for leave_type in leave_types:
            # Get policy for this staff and leave type
            policy = LeavePolicy.objects.filter(
                Q(campus=staff.campus) | Q(campus__isnull=True),
                leave_type=leave_type,
                is_active=True,
                accrual_method='MONTHLY'
            ).first()
            
            if not policy:
                continue
            
            # Calculate monthly accrual
            annual_entitlement = float(policy.annual_entitlement_days)
            monthly_accrual = Decimal(str(annual_entitlement / 12))
            
            # Get or create balance record
            balance, created = LeaveBalance.objects.get_or_create(
                staff=staff,
                leave_type=leave_type,
                year=accrual_year,
                defaults={
                    'total_entitled': Decimal(str(annual_entitlement)),
                    'earned_this_year': Decimal('0.00'),
                    'taken': Decimal('0.00'),
                    'pending': Decimal('0.00'),
                    'adjustments': Decimal('0.00'),
                }
            )
            
            if created:
                self.stdout.write(
                    f'  Created balance for {staff.full_name} - {leave_type.name} ({accrual_year})'
                )
            
            # Check if already accrued for this month
            existing_accrual = LeaveAccrual.objects.filter(
                staff=staff,
                leave_type=leave_type,
                accrual_date=accrual_date,
                transaction_type='MONTHLY_ACCRUAL'
            ).exists()
            
            if existing_accrual:
                self.stdout.write(
                    f'  Skipping {staff.full_name} - {leave_type.name}: Already accrued for {accrual_date}'
                )
                continue
            
            # Apply accrual
            if not dry_run:
                balance.earned_this_year += monthly_accrual
                balance.save()
                
                # Create accrual history record
                LeaveAccrual.objects.create(
                    staff=staff,
                    leave_type=leave_type,
                    accrual_date=accrual_date,
                    days_accrued=monthly_accrual,
                    transaction_type='MONTHLY_ACCRUAL',
                    notes=f'Monthly accrual for {accrual_date.strftime("%B %Y")}'
                )
            
            self.stdout.write(
                f'  ✓ {staff.full_name} - {leave_type.name}: +{monthly_accrual:.2f} days'
            )
