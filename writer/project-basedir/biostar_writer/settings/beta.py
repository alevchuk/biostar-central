from .prod import *

DATABASES['default']['NAME'] = 'beta'
DATABASES['default']['USER'] = 'beta_dbrw'

AWARD_TIMEDELTA = timedelta(minutes=1)
