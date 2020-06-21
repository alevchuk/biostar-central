from .prod import *

DATABASES['default']['NAME'] = 'beta'
DATABASES['default']['USER'] = 'beta_dbrw'

FRIENDLY_PREFIX = "beta.ln.support"  # cannot have under-bars (_s)

AWARD_TIMEDELTA = timedelta(minutes=1)
