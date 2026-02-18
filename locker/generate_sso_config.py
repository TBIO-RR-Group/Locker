#!/usr/bin/env python3
"""
Generate dynamic SSO configuration for SSOApache.pm from config.yml
This script updates the __DATA__ section of SSOApache.pm with current configuration
"""

import yaml
import os
import sys


def main():
    # Read configuration
    with open('/config.yml', 'r') as f:
        config = yaml.safe_load(f)

    # Extract SSO configuration
    cred_settings = config.get('credential_settings', {})
    locker_services = config.get('locker_services', {})

    # Build __DATA__ section content
    data_content = []
    data_content.append(f"SSO_SESSION_COOKIE_NAME\t{cred_settings.get('SSO_SESSION_COOKIE_NAME', 'BMSSSO')}")
    data_content.append(f"REDIRECT_TARGET_ARGNAME\t{cred_settings.get('REDIRECT_TARGET_ARGNAME', 'url')}")
    data_content.append(f"REDIRECT_URL\t{cred_settings.get('redirect_url', 'https://rdproxy.bms.com/rdproxyig/redirect.cgi')}")
    data_content.append(f"VALIDATE_URL\t{cred_settings.get('validate_url', 'https://rdproxy.bms.com/rdproxyig/validate.cgi')}")

    # Build list of authorized users (avoid duplicates)
    authorized_users = set()

    # Add admin users from config
    admin_users = locker_services.get('ADMIN_USERNAME', [])
    for admin in admin_users:
        authorized_users.add(admin)

    # Add the current running user
    current_user = os.environ.get('RUNASUSER', 'default_user')
    authorized_users.add(current_user)

    # Add users to data content
    for user in sorted(authorized_users):
        data_content.append(user)

    # Read the current SSOApache.pm file
    with open('/perl_mods/SSOApache.pm', 'r') as f:
        content = f.read()

    # Find the __DATA__ section and replace it
    data_section = '\n'.join(data_content)
    if '__DATA__' in content:
        # Split at __DATA__ and replace everything after it
        before_data = content.split('__DATA__')[0]
        new_content = before_data + '__DATA__\n' + data_section + '\n'
        
        # Write the updated content back
        with open('/perl_mods/SSOApache.pm', 'w') as f:
            f.write(new_content)
        
        print(f"Updated SSOApache.pm __DATA__ section with {len(data_content)} entries")
        print(f"Current user: {current_user}")
        print(f"Admin users: {admin_users}")
        print(f"Authorized users: {sorted(authorized_users)}")
    else:
        print("ERROR: __DATA__ section not found in SSOApache.pm")
        sys.exit(1)


if __name__ == '__main__':
    main()