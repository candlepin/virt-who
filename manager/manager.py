

class ManagerError(Exception):
    pass


class Manager(object):
    def sendVirtGuests(self, domains):
        raise NotImplementedError()

    def hypervisorCheckIn(self, owner, env, mapping, type=None):
        raise NotImplementedError()

    @classmethod
    def fromOptions(cls, logger, options):
        # Imports can't be top-level, it would be circular dependency
        import subscriptionmanager
        import satellite

        for subcls in cls.__subclasses__():
            if subcls.smType == options.smType:
                return subcls(logger, options)

        raise KeyError("Invalid config type: %s" % options.smType)
