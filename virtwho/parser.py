
import os
from optparse import OptionParser, OptionGroup, SUPPRESS_HELP

from virtwho import log, MinimumSendInterval, DefaultInterval
from virtwho.config import GlobalConfig, NotSetSentinel, VIRTWHO_GENERAL_CONF_PATH


SAT5 = "satellite"
SAT6 = "sam"


class OptionError(Exception):
    pass


class OptionParserEpilog(OptionParser):
    """ Epilog is new in Python 2.5, we need to support Python 2.4. """
    def __init__(self, usage="%prog [options]", description=None, epilog=None):
        self.myepilog = epilog
        OptionParser.__init__(self, usage=usage, description=description)

    def format_help(self, formatter=None):
        if formatter is None:
            formatter = self.formatter
        help = OptionParser.format_help(self, formatter)
        return help + "\n" + self.format_myepilog(formatter) + "\n"

    def format_myepilog(self, formatter=None):
        if self.myepilog is not None:
            return formatter.format_description(self.myepilog)
        else:
            return ""


def parseOptions():
    parser = OptionParserEpilog(usage="virt-who [-d] [-i INTERVAL] [-o] [--sam|--satellite5|--satellite6] [--libvirt|--vdsm|--esx|--rhevm|--hyperv|--xen]",
                                description="Agent for reporting virtual guest IDs to subscription manager",
                                epilog="virt-who also reads enviroment variables. They have the same name as command line arguments but uppercased, with underscore instead of dash and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are considered as disabled, non-empty as enabled")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-o", "--one-shot", action="store_true", dest="oneshot", default=False, help="Send the list of guest IDs and exit immediately")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=NotSetSentinel(), help="Acquire list of virtual guest each N seconds. Send if changes are detected.")
    parser.add_option("-p", "--print", action="store_true", dest="print_", default=False, help="Print the host/guest association obtained from virtualization backend (implies oneshot)")
    parser.add_option("-c", "--config", action="append", dest="configs", default=[], help="Configuration file that will be processed, can be used multiple times")
    parser.add_option("-m", "--log-per-config", action="store_true", dest="log_per_config", default=NotSetSentinel(), help="Write one log file per configured virtualization backend.\nImplies a log_dir of %s/virtwho (Default: all messages are written to a single log file)" % log.DEFAULT_LOG_DIR)
    parser.add_option("-l", "--log-dir", action="store", dest="log_dir", default=log.DEFAULT_LOG_DIR, help="The absolute path of the directory to log to. (Default '%s')" % log.DEFAULT_LOG_DIR)
    parser.add_option("-f", "--log-file", action="store", dest="log_file", default=log.DEFAULT_LOG_FILE, help="The file name to write logs to. (Default '%s')" % log.DEFAULT_LOG_FILE)
    parser.add_option("-r", "--reporter-id", action="store", dest="reporter_id", default=NotSetSentinel(), help="Label host/guest associations obtained by this instance of virt-who with the provided id.")

    virtGroup = OptionGroup(parser, "Virtualization backend", "Choose virtualization backend that should be used to gather host/guest associations")
    virtGroup.add_option("--libvirt", action="store_const", dest="virtType", const="libvirt", default=None, help="Use libvirt to list virtual guests [default]")
    virtGroup.add_option("--vdsm", action="store_const", dest="virtType", const="vdsm", help="Use vdsm to list virtual guests")
    virtGroup.add_option("--esx", action="store_const", dest="virtType", const="esx", help="Register ESX machines using vCenter")
    virtGroup.add_option("--xen", action="store_const", dest="virtType", const="xen", help="Register XEN machines using XenServer")
    virtGroup.add_option("--rhevm", action="store_const", dest="virtType", const="rhevm", help="Register guests using RHEV-M")
    virtGroup.add_option("--hyperv", action="store_const", dest="virtType", const="hyperv", help="Register guests using Hyper-V")
    parser.add_option_group(virtGroup)

    managerGroup = OptionGroup(parser, "Subscription manager", "Choose where the host/guest associations should be reported")
    managerGroup.add_option("--sam", action="store_const", dest="smType", const=SAT6, default=SAT6, help="Report host/guest associations to the Subscription Asset Manager [default]")
    managerGroup.add_option("--satellite6", action="store_const", dest="smType", const=SAT6, help="Report host/guest associations to the Satellite 6 server")
    managerGroup.add_option("--satellite5", action="store_const", dest="smType", const=SAT5, help="Report host/guest associations to the Satellite 5 server")
    managerGroup.add_option("--satellite", action="store_const", dest="smType", const=SAT5, help=SUPPRESS_HELP)
    parser.add_option_group(managerGroup)

    libvirtGroup = OptionGroup(parser, "Libvirt options", "Use these options with --libvirt")
    libvirtGroup.add_option("--libvirt-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products, default is owner of current system")
    libvirtGroup.add_option("--libvirt-env", action="store", dest="env", default="", help="Environment where the server belongs to, default is environment of current system")
    libvirtGroup.add_option("--libvirt-server", action="store", dest="server", default="", help="URL of the libvirt server to connect to, default is empty for libvirt on local computer")
    libvirtGroup.add_option("--libvirt-username", action="store", dest="username", default="", help="Username for connecting to the libvirt daemon")
    libvirtGroup.add_option("--libvirt-password", action="store", dest="password", default="", help="Password for connecting to the libvirt daemon")
    parser.add_option_group(libvirtGroup)

    esxGroup = OptionGroup(parser, "vCenter/ESX options", "Use these options with --esx")
    esxGroup.add_option("--esx-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    esxGroup.add_option("--esx-env", action="store", dest="env", default="", help="Environment where the vCenter server belongs to")
    esxGroup.add_option("--esx-server", action="store", dest="server", default="", help="URL of the vCenter server to connect to")
    esxGroup.add_option("--esx-username", action="store", dest="username", default="", help="Username for connecting to vCenter")
    esxGroup.add_option("--esx-password", action="store", dest="password", default="", help="Password for connecting to vCenter")
    parser.add_option_group(esxGroup)

    rhevmGroup = OptionGroup(parser, "RHEV-M options", "Use these options with --rhevm")
    rhevmGroup.add_option("--rhevm-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    rhevmGroup.add_option("--rhevm-env", action="store", dest="env", default="", help="Environment where the RHEV-M belongs to")
    rhevmGroup.add_option("--rhevm-server", action="store", dest="server", default="", help="URL of the RHEV-M server to connect to (preferable use secure connection - https://<ip or domain name>:<secure port, usually 8443>)")
    rhevmGroup.add_option("--rhevm-username", action="store", dest="username", default="", help="Username for connecting to RHEV-M in the format username@domain")
    rhevmGroup.add_option("--rhevm-password", action="store", dest="password", default="", help="Password for connecting to RHEV-M")
    parser.add_option_group(rhevmGroup)

    hypervGroup = OptionGroup(parser, "Hyper-V options", "Use these options with --hyperv")
    hypervGroup.add_option("--hyperv-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    hypervGroup.add_option("--hyperv-env", action="store", dest="env", default="", help="Environment where the Hyper-V belongs to")
    hypervGroup.add_option("--hyperv-server", action="store", dest="server", default="", help="URL of the Hyper-V server to connect to")
    hypervGroup.add_option("--hyperv-username", action="store", dest="username", default="", help="Username for connecting to Hyper-V")
    hypervGroup.add_option("--hyperv-password", action="store", dest="password", default="", help="Password for connecting to Hyper-V")
    parser.add_option_group(hypervGroup)

    xenGroup = OptionGroup(parser, "XenServer options", "Use these options with --xen")
    xenGroup.add_option("--xen-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    xenGroup.add_option("--xen-env", action="store", dest="env", default="", help="Environment where the XenServer belongs to")
    xenGroup.add_option("--xen-server", action="store", dest="server", default="", help="URL of the XenServer server to connect to")
    xenGroup.add_option("--xen-username", action="store", dest="username", default="", help="Username for connecting to XenServer")
    xenGroup.add_option("--xen-password", action="store", dest="password", default="", help="Password for connecting to XenServer")
    parser.add_option_group(xenGroup)

    satelliteGroup = OptionGroup(parser, "Satellite 5 options", "Use these options with --satellite5")
    satelliteGroup.add_option("--satellite-server", action="store", dest="sat_server", default="", help="Satellite server URL")
    satelliteGroup.add_option("--satellite-username", action="store", dest="sat_username", default="", help="Username for connecting to Satellite server")
    satelliteGroup.add_option("--satellite-password", action="store", dest="sat_password", default="", help="Password for connecting to Satellite server")
    parser.add_option_group(satelliteGroup)

    (cli_options, args) = parser.parse_args()

    options = GlobalConfig.fromFile(VIRTWHO_GENERAL_CONF_PATH)

    # Handle defaults from the command line options parser

    options.update(**parser.defaults)

    # Handle enviroment variables

    env = os.getenv("VIRTWHO_LOG_PER_CONFIG", "0").strip().lower()
    if env in ["1", "true"]:
        options.log_per_config = True

    env = os.getenv("VIRTWHO_LOG_DIR", log.DEFAULT_LOG_DIR).strip()
    if env != log.DEFAULT_LOG_DIR:
        options.log_dir = env
    elif options.log_per_config:
        options.log_dir = os.path.join(log.DEFAULT_LOG_DIR, 'virtwho')

    env = os.getenv("VIRTWHO_LOG_FILE", log.DEFAULT_LOG_FILE).strip()
    if env != log.DEFAULT_LOG_FILE:
        options.log_file = env

    env = os.getenv("VIRTWHO_REPORTER_ID", "").strip()
    if len(env) > 0:
        options.reporter_id = env

    env = os.getenv("VIRTWHO_DEBUG", "0").strip().lower()
    if env in ["1", "true"] or cli_options.debug is True:
        options.debug = True

    # Used only when starting as service (initscript sets it to 1, systemd to 0)
    env = os.getenv("VIRTWHO_BACKGROUND", "0").strip().lower()
    options.background = env in ["1", "true"]

    log.init(options)
    logger = log.getLogger(name='init', queue=False)

    env = os.getenv("VIRTWHO_ONE_SHOT", "0").strip().lower()
    if env in ["1", "true"]:
        options.oneshot = True

    env = os.getenv("VIRTWHO_INTERVAL")
    if env:
        env = env.strip().lower()
    try:
        if env and int(env) >= MinimumSendInterval:
            options.interval = int(env)
    except ValueError:
        logger.warning("Interval is not number, ignoring")

    env = os.getenv("VIRTWHO_SAM", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT6

    env = os.getenv("VIRTWHO_SATELLITE6", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT6

    env = os.getenv("VIRTWHO_SATELLITE5", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT5

    env = os.getenv("VIRTWHO_SATELLITE", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT5

    env = os.getenv("VIRTWHO_LIBVIRT", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "libvirt"

    env = os.getenv("VIRTWHO_VDSM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "vdsm"

    env = os.getenv("VIRTWHO_ESX", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "esx"

    env = os.getenv("VIRTWHO_XEN", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "xen"

    env = os.getenv("VIRTWHO_RHEVM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "rhevm"

    env = os.getenv("VIRTWHO_HYPERV", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "hyperv"

    def getNonDefaultOptions(cli_options, defaults):
        return dict((option, value) for option, value in cli_options.iteritems()
                    if defaults.get(option, NotSetSentinel()) != value)

    # Handle non-default command line options
    options.update(**getNonDefaultOptions(vars(cli_options), parser.defaults))

    # Check Env
    def checkEnv(variable, option, name, required=True):
        """
        If `option` is empty, check enviroment `variable` and return its value.
        Exit if it's still empty
        """
        if not option or len(option) == 0:
            option = os.getenv(variable, "").strip()
        if required and (not option or len(option) == 0):
            raise OptionError("Required parameter '%s' is not set, exiting" % name)
        return option

    if options.smType == SAT5:
        options.sat_server = checkEnv("VIRTWHO_SATELLITE_SERVER", options.sat_server, "satellite-server")
        options.sat_username = checkEnv("VIRTWHO_SATELLITE_USERNAME", options.sat_username, "satellite-username")
        if len(options.sat_password) == 0:
            options.sat_password = os.getenv("VIRTWHO_SATELLITE_PASSWORD", "")

    if options.virtType == "libvirt":
        options.owner = checkEnv("VIRTWHO_LIBVIRT_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_LIBVIRT_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_LIBVIRT_SERVER", options.server, "server", required=False)
        options.username = checkEnv("VIRTWHO_LIBVIRT_USERNAME", options.username, "username", required=False)
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_LIBVIRT_PASSWORD", "")

    if options.virtType == "esx":
        options.owner = checkEnv("VIRTWHO_ESX_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_ESX_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_ESX_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_ESX_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_ESX_PASSWORD", "")

    if options.virtType == "xen":
        options.owner = checkEnv("VIRTWHO_XEN_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_XEN_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_XEN_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_XEN_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_XEN_PASSWORD", "")

    if options.virtType == "rhevm":
        options.owner = checkEnv("VIRTWHO_RHEVM_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_RHEVM_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_RHEVM_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_RHEVM_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_RHEVM_PASSWORD", "")

    if options.virtType == "hyperv":
        options.owner = checkEnv("VIRTWHO_HYPERV_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_HYPERV_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_HYPERV_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_HYPERV_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_HYPERV_PASSWORD", "")

    if options.smType == 'sam' and options.virtType in ('esx', 'rhevm', 'hyperv', 'xen'):
        if not options.owner:
            raise OptionError("Option --%s-owner (or VIRTWHO_%s_OWNER environment variable) needs to be set" % (options.virtType, options.virtType.upper()))
        if not options.env:
            raise OptionError("Option --%s-env (or VIRTWHO_%s_ENV environment variable) needs to be set" % (options.virtType, options.virtType.upper()))

    if options.interval < MinimumSendInterval:
        if not options.interval or options.interval == parser.defaults['interval']:
            logger.info("Interval set to the default of %d seconds.", DefaultInterval)
        else:
            logger.warning("Interval value can't be lower than {min} seconds. Default value of {min} seconds will be used.".format(min=MinimumSendInterval))
        options.interval = MinimumSendInterval

    if options.print_:
        options.oneshot = True

    return logger, options
