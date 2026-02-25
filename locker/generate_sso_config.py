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

    # Build list of authorized users with roles (avoid duplicates)
    # Owner + admins get 'full' access; custom authorized users get 'restricted'
    full_users = set()
    restricted_users = set()

    # Add admin users from config as full-access
    admin_users = locker_services.get('ADMIN_USERNAME', [])
    for admin in admin_users:
        full_users.add(admin)

    # Add the current running user as full-access
    current_user = os.environ.get('RUNASUSER', 'default_user')
    full_users.add(current_user)

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
                    restricted_users.add(user)
                if custom_users:
                    print(f"Loaded {len(custom_users)} custom authorized users from {config_json_path}")
    except Exception as e:
        print(f"Warning: Could not load custom authorized users from config.json: {e}")

    # Remove any restricted users who are already full-access (owner/admin)
    restricted_users -= full_users

    # Add role-annotated user lines to data content
    for user in sorted(full_users):
        data_content.append(f"{user}\tfull")
    for user in sorted(restricted_users):
        data_content.append(f"{user}\trestricted")

    authorized_users = full_users | restricted_users

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
            for user in sorted(full_users):
                f.write(f"{user}\tfull\n")
            for user in sorted(restricted_users):
                f.write(f"{user}\trestricted\n")
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