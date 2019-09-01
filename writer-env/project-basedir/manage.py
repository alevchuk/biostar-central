#!/usr/bin/env python
import os
import sys

def create_live_dir():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    LIVE_DIR = '{}/live'.format(BASE_DIR)
    LIVE_DIR_ACCESS_RIGHTS = 0o755
    
    try:  
        os.mkdir(LIVE_DIR, LIVE_DIR_ACCESS_RIGHTS)
    except FileExistsError:
        pass
    else:  
        print('Created new directory {}'.format(LIVE_DIR))

if __name__ == '__main__':
    create_live_dir()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'biostar_writer.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
