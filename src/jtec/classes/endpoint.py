class Endpoint:
    def __init__(
        self,
        name="",
        url="",
        enabled=True,
        group="",
        method="GET",
        conditions=[],
        interval="60s",
        graphql=False,
        body="",
        headers={},
        dns="",
        ssh="",
        alerts=[],
        maintenance_windows=[],
        client={},
        ui={
            "hide_conditions": False,
            "hide_hostname": False,
            "hide_port": False,
            "hide_url": False,
            "dont_resolve_failed_conditions": False,
            "badge": {"response_time": [50, 200, 300, 500, 750]},
        },
    ):
        # Required fields validation
        if not name:
            raise ValueError("Endpoint name is required")
        if not url:
            raise ValueError("Endpoint URL is required")

        self.name = name
        self.url = url
        self.enabled = self._str_to_bool(enabled)
        self.group = group
        self.method = method
        self.conditions = conditions
        self.interval = interval
        self.graphql = graphql
        self.body = body
        self.headers = headers
        self.dns = dns
        self.ssh = ssh
        self.alerts = alerts
        self.maintenance_windows = maintenance_windows
        self.client = client
        self.ui = ui

    @staticmethod
    def _str_to_bool(value):
        """Convert string to boolean, leave boolean values unchanged."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "yes", "y", "1"):
                return True
            elif value.lower() in ("false", "no", "n", "0"):
                return False
            else:
                raise ValueError(f"Cannot convert '{value}' to boolean")
        raise TypeError(f"Expected string or boolean, got {type(value).__name__}")

    def __str__(self):
        return f"Endpoint: {self.name} - {self.url} ({self.method})"

    def to_dict(self):
        """Convert the endpoint object to a dictionary"""
        return {
            "name": self.name,
            "url": self.url,
            "enabled": self.enabled,
            "group": self.group,
            "method": self.method,
            "conditions": self.conditions,
            "interval": self.interval,
            "graphql": self.graphql,
            "body": self.body,
            "headers": self.headers,
            "dns": self.dns,
            "ssh": self.ssh,
            "alerts": self.alerts,
            "maintenance_windows": self.maintenance_windows,
            "client": self.client,
            "ui": self.ui,
        }
