from biostar.settings.deploy import *

DATABASES['default']['NAME'] = 'beta'
DATABASES['default']['USER'] = 'beta_dbro'

FRIENDLY_PREFIX = "beta.ln.support"  # cannot have under-bars (_s)
