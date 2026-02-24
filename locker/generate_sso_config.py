#!/usr/bin/env python3
"""
Generate dynamic SSO configuration for SSOApache.pm from config.yml
This script updates the __DATA__ section of SSOApache.pm with current configuration
"""

import yaml
import os
import re
import sys
import json


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

    # Load custom authorized users from user's config.json (if it exists)
    try:
        user_homedir = os.environ.get('USER_HOMEDIR', '')
        user_config_dir_name = locker_services.get('userConfigDirName', '.locker')
        if user_homedir:
            config_json_path = os.path.join('/host_root' + user_homedir, user_config_dir_name, 'config.json')
            if os.path.exists(config_json_path):
                with open(config_json_path, 'r') as f:
                    user_config = json.load(f)
                custom_users = user_config.get('config_authorized_users', [])
                for user in custom_users:
                    authorized_users.add(user)
                if custom_users:
                    print(f"Loaded {len(custom_users)} custom authorized users from {config_json_path}")
    except Exception as e:
        print(f"Warning: Could not load custom authorized users from config.json: {e}")

    # Add users to data content
    for user in sorted(authorized_users):
        data_content.append(user)

    # Read the current SSOApache.pm file
    with open('/perl_mods/SSOApache.pm', 'r') as f:
        content = f.read()

    # Find the __DATA__ section (as a standalone line) and replace it
    data_section = '\n'.join(data_content)
    parts = re.split(r'^__DATA__\s*$', content, maxsplit=1, flags=re.MULTILINE)
    if len(parts) == 2:
        before_data = parts[0]
        new_content = before_data + '__DATA__\n' + data_section + '\n'
        
        # Write the updated content back
        with open('/perl_mods/SSOApache.pm', 'w') as f:
            f.write(new_content)

        # Make writable so the Flask app (running as non-root) can update it at runtime
        os.chmod('/perl_mods/SSOApache.pm', 0o666)

        # Write external authorized users file for dynamic reload by SSOApache.pm
        ext_users_file = '/tmp/sso_authorized_users.txt'
        with open(ext_users_file, 'w') as f:
            for user in sorted(authorized_users):
                f.write(user + '\n')
        os.chmod(ext_users_file, 0o666)
        print(f"Wrote {len(authorized_users)} users to {ext_users_file}")

        print(f"Updated SSOApache.pm __DATA__ section with {len(data_content)} entries")
        print(f"Current user: {current_user}")
        print(f"Admin users: {admin_users}")
        print(f"Authorized users: {sorted(authorized_users)}")
    else:
        print("ERROR: __DATA__ section not found in SSOApache.pm")
        sys.exit(1)


if __name__ == '__main__':
    main()