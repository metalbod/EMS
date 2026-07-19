#!/usr/bin/env python3
"""
Load sample compensation data to EMS API.

Usage:
    python seeds/load_compensation_to_api.py \
        --api-url https://ems-app.fly.dev \
        --token YOUR_HR_MANAGER_TOKEN

Example with environment variables:
    export EMS_API_URL=https://ems-app.fly.dev
    export EMS_TOKEN=$(cat ~/.ems_token)
    python seeds/load_compensation_to_api.py

If using localhost:
    python seeds/load_compensation_to_api.py --api-url http://localhost:8000
"""

import requests
import sys
import argparse
from typing import Optional, Dict, Any
from seeds.compensation_setup_software import SAMPLE_DATA


class CompensationSeeder:
    def __init__(self, api_url: str, token: str, verbose: bool = False):
        self.api_url = api_url.rstrip('/')
        self.token = token
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        })
        self.created_ids = {
            'pay_grades': {},
            'job_levels': {},
            'job_roles': {},
        }

    def log(self, message: str, level: str = 'INFO'):
        if self.verbose or level in ['ERROR', 'SUCCESS']:
            prefix = '  ✓' if level == 'SUCCESS' else '  ✗' if level == 'ERROR' else '  »'
            print(f"{prefix} {message}")

    def seed_pay_grades(self) -> bool:
        """Load pay grades from sample data."""
        print("\n📊 Loading Pay Grades...")
        for grade_data in SAMPLE_DATA['pay_grades']:
            try:
                res = self.session.post(
                    f"{self.api_url}/api/compensation/pay-grades",
                    json=grade_data
                )
                if res.status_code == 201:
                    grade = res.json()
                    self.created_ids['pay_grades'][grade_data['grade_code']] = grade['id']
                    self.log(f"{grade_data['grade_code']:5} ({grade_data['grade_name']}) → ID {grade['id']}", 'SUCCESS')
                else:
                    self.log(f"Failed to create {grade_data['grade_code']}: {res.text}", 'ERROR')
                    return False
            except Exception as e:
                self.log(f"Error creating {grade_data['grade_code']}: {e}", 'ERROR')
                return False
        return True

    def seed_job_levels(self) -> bool:
        """Load job levels from sample data."""
        print("\n📈 Loading Job Levels...")
        for level_data in SAMPLE_DATA['job_levels']:
            try:
                res = self.session.post(
                    f"{self.api_url}/api/compensation/job-levels",
                    json=level_data
                )
                if res.status_code == 201:
                    level = res.json()
                    self.created_ids['job_levels'][level_data['level_code']] = level['id']
                    self.log(f"{level_data['level_code']:15} ({level_data['level_name']}) → ID {level['id']}", 'SUCCESS')
                else:
                    self.log(f"Failed to create {level_data['level_code']}: {res.text}", 'ERROR')
                    return False
            except Exception as e:
                self.log(f"Error creating {level_data['level_code']}: {e}", 'ERROR')
                return False
        return True

    def seed_job_roles(self) -> bool:
        """Load job roles from sample data."""
        print("\n👨‍💼 Loading Job Roles...")
        for role_data in SAMPLE_DATA['job_roles']:
            # Map level_code to level_id
            level_code = role_data.pop('level_code')
            if level_code not in self.created_ids['job_levels']:
                self.log(f"Unknown level_code '{level_code}' for role {role_data.get('role_code')}", 'ERROR')
                return False

            role_data['job_level_id'] = self.created_ids['job_levels'][level_code]

            try:
                res = self.session.post(
                    f"{self.api_url}/api/compensation/job-roles",
                    json=role_data
                )
                if res.status_code == 201:
                    role = res.json()
                    self.created_ids['job_roles'][role_data['role_code']] = role['id']
                    self.log(f"{role_data['role_code']:10} ({role_data['role_name']}) → ID {role['id']}", 'SUCCESS')
                else:
                    self.log(f"Failed to create {role_data['role_code']}: {res.text}", 'ERROR')
                    return False
            except Exception as e:
                self.log(f"Error creating {role_data['role_code']}: {e}", 'ERROR')
                return False
        return True

    def seed_merit_cycles(self) -> bool:
        """Load merit review cycles from sample data."""
        print("\n🎯 Loading Merit Review Cycles...")
        for cycle_data in SAMPLE_DATA['merit_cycles']:
            try:
                res = self.session.post(
                    f"{self.api_url}/api/compensation/merit-cycles",
                    json=cycle_data
                )
                if res.status_code == 201:
                    cycle = res.json()
                    self.log(f"{cycle_data['cycle_name']} → ID {cycle['id']}", 'SUCCESS')
                else:
                    self.log(f"Failed to create {cycle_data['cycle_name']}: {res.text}", 'ERROR')
                    return False
            except Exception as e:
                self.log(f"Error creating {cycle_data['cycle_name']}: {e}", 'ERROR')
                return False
        return True

    def seed_role_to_grade_mapping(self) -> bool:
        """Map job roles to pay grades (typical mapping for software companies)."""
        print("\n🔗 Mapping Roles to Pay Grades...")

        # Define typical role → grade mappings for software company
        mappings = {
            'ENG_JR': ['IC1'],
            'ENG_1': ['IC1', 'IC2'],
            'ENG_2': ['IC2', 'IC3'],
            'FE_2': ['IC2', 'IC3'],
            'BE_2': ['IC2', 'IC3'],
            'ENG_SR': ['IC3', 'IC4'],
            'FE_SR': ['IC3', 'IC4'],
            'BE_SR': ['IC3', 'IC4'],
            'ENG_STAFF': ['IC4'],
            'TECH_LEAD': ['L1'],
            'ENG_MGR': ['M1'],
            'ENG_SR_MGR': ['M2'],
            'ENG_DIR': ['D1'],
        }

        for role_code, grade_codes in mappings.items():
            if role_code not in self.created_ids['job_roles']:
                self.log(f"Role {role_code} not found in created roles", 'ERROR')
                continue

            role_id = self.created_ids['job_roles'][role_code]
            for grade_code in grade_codes:
                if grade_code not in self.created_ids['pay_grades']:
                    self.log(f"Grade {grade_code} not found for role {role_code}", 'ERROR')
                    continue

                grade_id = self.created_ids['pay_grades'][grade_code]
                try:
                    res = self.session.post(
                        f"{self.api_url}/api/compensation/job-roles/{role_id}/pay-grades/{grade_id}",
                        json={}
                    )
                    if res.status_code == 201:
                        self.log(f"{role_code:10} → {grade_code:5} (primary: {grade_code == grade_codes[0]})", 'SUCCESS')
                    else:
                        self.log(f"Failed to map {role_code} → {grade_code}: {res.text}", 'ERROR')
                except Exception as e:
                    self.log(f"Error mapping {role_code} → {grade_code}: {e}", 'ERROR')

        return True

    def verify_health(self) -> bool:
        """Verify API is reachable and authenticated."""
        try:
            res = self.session.get(f"{self.api_url}/api/health")
            if res.status_code != 200:
                print(f"❌ API health check failed: {res.status_code}")
                return False
            print("✅ API is healthy")
            return True
        except Exception as e:
            print(f"❌ Cannot reach API at {self.api_url}: {e}")
            return False

    def run(self) -> bool:
        """Execute full seeding process."""
        print("\n" + "=" * 70)
        print("  COMPENSATION FRAMEWORK - SAMPLE DATA LOADER")
        print("  Loading data into: " + self.api_url)
        print("=" * 70)

        if not self.verify_health():
            return False

        # Load data in dependency order
        if not self.seed_pay_grades():
            return False
        if not self.seed_job_levels():
            return False
        if not self.seed_job_roles():
            return False
        if not self.seed_role_to_grade_mapping():
            return False
        if not self.seed_merit_cycles():
            return False

        print("\n" + "=" * 70)
        print("✨ SEEDING COMPLETE!")
        print("=" * 70)
        print(f"\n📊 Summary:")
        print(f"   Pay Grades:      {len(self.created_ids['pay_grades'])} created")
        print(f"   Job Levels:      {len(self.created_ids['job_levels'])} created")
        print(f"   Job Roles:       {len(self.created_ids['job_roles'])} created")
        print(f"   Merit Cycles:    {len(SAMPLE_DATA['merit_cycles'])} created")
        print(f"\n🎯 Next steps:")
        print(f"   1. Navigate to Settings → Compensation")
        print(f"   2. Verify pay grades, job levels, and roles are visible")
        print(f"   3. Assign compensation to employees")
        print(f"   4. Create merit recommendations")
        return True


def main():
    parser = argparse.ArgumentParser(
        description='Load sample compensation data to EMS API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--api-url',
        default='https://ems-app.fly.dev',
        help='API base URL (default: https://ems-app.fly.dev)'
    )
    parser.add_argument(
        '--token',
        help='Bearer token for authentication'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    # Get token from args or env
    token = args.token or None
    if not token:
        import os
        token = os.getenv('EMS_TOKEN') or os.getenv('COMPENSATION_SEED_TOKEN')

    if not token:
        print("❌ Error: No authentication token provided")
        print("\nProvide token via:")
        print("  --token <your-token>")
        print("  export EMS_TOKEN=<your-token>")
        print("  export COMPENSATION_SEED_TOKEN=<your-token>")
        sys.exit(1)

    seeder = CompensationSeeder(args.api_url, token, verbose=args.verbose)
    success = seeder.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
