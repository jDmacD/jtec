import click
import yaml
from kubernetes import client, config

from .endpoint import Endpoint


# Define a custom class for handling headers in key=value format
class HeaderParamType(click.ParamType):
    name = "header"

    def convert(self, value, param, ctx):
        if "=" not in value:
            self.fail(
                f"Header must be in format 'Key=Value', got '{value}'", param, ctx
            )
        key, val = value.split("=", 1)
        if not key:
            self.fail("Header key cannot be empty", param, ctx)
        return (key, val)


HEADER_TYPE = HeaderParamType()


def get_ingresses(kubeconfig, context):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig, context=context)
    else:
        try:
            config.load_kube_config(context=context)
        except config.config_exception.ConfigException:
            config.load_incluster_config()

    # Initialize the networking API client
    v1 = client.NetworkingV1Api()

    # Get all Ingresses from all namespaces
    ingresses = v1.list_ingress_for_all_namespaces()

    return ingresses


def process_ingresses(
    ingresses, endpoints, interval, status_code, response_time, header, group=None, alerts=None
):
    # Process each Ingress
    for ingress in ingresses.items:
        name = ingress.metadata.name
        namespace = ingress.metadata.namespace

        click.echo(f"found ingress {namespace}/{name}")

        # Get annotations
        annotations = ingress.metadata.annotations or {}

        # Process each rule
        if ingress.spec.rules:
            for i, rule in enumerate(ingress.spec.rules):
                if not rule.host:
                    continue

                path = annotations.get("gatus.io/path", "")

                # Generate URL
                url = f"https://{rule.host}{path}"

                # Get endpoint name from annotation or fallback to ingress name
                endpoint_name = annotations.get("gatus.io/name", name)
                # Only append index if using fallback name and multiple rules exist
                if endpoint_name == name and len(ingress.spec.rules) > 1:
                    endpoint_name = f"{endpoint_name}[{i + 1}]"

                endpoint = Endpoint(
                    name=endpoint_name,
                    url=url,
                    enabled=annotations.get("gatus.io/enabled", True),
                    # Use group if provided, otherwise use namespace
                    group=group if group is not None else namespace,
                    interval=annotations.get("gatus.io/interval", interval),
                    conditions=generate_conditions(
                        annotations, status_code, response_time
                    ),
                    headers=generate_headers(annotations, header),
                    alerts=alerts if alerts else []
                )
                endpoints.append(endpoint.to_dict())


def get_httproutes(kubeconfig, context):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig, context=context)
    else:
        try:
            config.load_kube_config(context=context)
        except config.config_exception.ConfigException:
            config.load_incluster_config()

    # Initialize the custom API client for gateway API
    api_client = client.ApiClient()
    custom_api = client.CustomObjectsApi(api_client)

    # Get all HTTPRoutes from all namespaces
    httproutes = custom_api.list_cluster_custom_object(
        group="gateway.networking.k8s.io", version="v1beta1", plural="httproutes"
    )

    return httproutes


def process_httproutes(
    httproutes, endpoints, interval, status_code, response_time, header, group=None, alerts=None
):
    # Process each HTTPRoute
    for route in httproutes.get("items", []):
        name = route["metadata"]["name"]
        hostnames = route["spec"].get("hostnames", [])

        click.echo(f"found httproute {name}")

        # Skip if no hostnames
        if not hostnames:
            continue

        # Get parent ref name (gateway)
        parent_refs = route["spec"].get("parentRefs", [])
        parent_ref_name = parent_refs[0]["name"] if parent_refs else "default-gateway"

        # Get annotations
        annotations = route["metadata"].get("annotations", {})

        for i, hostname in enumerate(hostnames):
            # Clean hostname
            clean_hostname = hostname.strip()
            if not clean_hostname:
                continue

            path = annotations.get("gatus.io/path", "")

            # Generate URL
            url = f"https://{clean_hostname}{path}"

            # Get endpoint name from annotation or fallback to route name
            endpoint_name = annotations.get("gatus.io/name", name)
            # Only append index if using fallback name and multiple hostnames exist
            if endpoint_name == name and len(hostnames) > 1:
                endpoint_name = f"{endpoint_name}[{i + 1}]"

            endpoint = Endpoint(
                name=endpoint_name,
                url=url,
                enabled=annotations.get("gatus.io/enabled", True),
                # Use group if provided, otherwise use parent_ref_name
                group=group if group is not None else parent_ref_name,
                interval=annotations.get("gatus.io/interval", interval),
                conditions=generate_conditions(annotations, status_code, response_time),
                headers=generate_headers(annotations, header),
                alerts=alerts if alerts else []
            )
            endpoints.append(endpoint.to_dict())


def generate_conditions(annotations, status_code, response_time):
    # Setup default conditions
    default_conditions = {
        "status": f"== {status_code}",
        "response-time": f"< {response_time}",
    }

    conditions = []

    # Process all conditions from annotations and defaults
    for key, value in annotations.items():
        if key.startswith("gatus.io/conditions."):
            condition_name = key.replace("gatus.io/conditions.", "")
            default_conditions.pop(
                condition_name, None
            )  # Remove from defaults if overridden
            condition_name = condition_name.upper().replace("-", "_")
            conditions.append(f"[{condition_name}] {value.strip()}")

    # Add any remaining default conditions
    for condition_name, value in default_conditions.items():
        formatted_name = condition_name.upper().replace("-", "_")
        conditions.append(f"[{formatted_name}] {value}")

    return conditions


def generate_headers(annotations, header):
    headers = {}
    if header:
        for key, value in header:
            headers[key] = value

    for key, value in annotations.items():
        if key.startswith("gatus.io/header."):
            header_name = key.replace("gatus.io/header.", "")
            headers[header_name] = value

    return headers

def validate_unique_names(endpoints):
    """Validate that there are no duplicate endpoint names within the same group."""
    # Create a dictionary to store name-group combinations
    seen = {}
    
    for endpoint in endpoints:
        key = (endpoint['name'], endpoint['group'])
        if key in seen:
            # If we find a duplicate, raise an error with details
            raise click.ClickException(
                f"Duplicate endpoint name '{endpoint['name']}' found in group '{endpoint['group']}'. "
                f"Each endpoint name must be unique within its group.\n"
                f"First occurrence URL: {seen[key]}\n"
                f"Duplicate URL: {endpoint['url']}"
            )
        seen[key] = endpoint['url']

@click.command("gatus", short_help="creates a gatus configuration")
@click.option(
    "--output",
    "-o",
    default="endpoints.yaml",
    help="Output YAML file",
    envvar="OUTPUT_FILE",
)
@click.option("--kubeconfig", help="Path to kubeconfig file", envvar="KUBECONFIG")
@click.option("--context", help="Kubernetes context to use", envvar="KUBE_CONTEXT")
@click.option(
    "--interval",
    default="5m",
    help="Default check interval (e.g., 5m, 1h)",
    envvar="DEFAULT_INTERVAL",
)
@click.option(
    "--status-code",
    default="200",
    help="Default expected status code",
    envvar="DEFAULT_STATUS_CODE",
)
@click.option(
    "--response-time",
    default="5000",
    help="Default maximum response time in ms",
    envvar="DEFAULT_RESPONSE_TIME",
)
@click.option(
    "--header",
    "-H",
    multiple=True,
    type=HEADER_TYPE,
    help='Custom header in format "Key=Value" or "Key=$ENV_VAR" (can be used multiple times)',
    envvar="DEFAULT_HEADERS",
)
@click.option(
    "--include-ingress/--no-include-ingress",
    default=True,
    help="Include Ingress resources in the configuration",
    envvar="INCLUDE_INGRESS",
)
@click.option(
    "--include-httproute/--no-include-httproute",
    default=True,
    help="Include HTTPRoute resources in the configuration",
    envvar="INCLUDE_HTTPROUTE",
)
@click.option('--group', required=False, help='Optional group name for all endpoints')
@click.option(
    '--alert',
    multiple=True,
    help='Alert configuration to add to endpoints (can be specified multiple times)',
)
def main(
    output,
    kubeconfig,
    context,
    interval,
    status_code,
    response_time,
    header,
    include_ingress,
    include_httproute,
    group,
    alert
):
    endpoints = []

    alerts = [{"type": a} for a in alert] if alert else None

    if include_httproute:
        httproutes = get_httproutes(kubeconfig, context)
        process_httproutes(
            httproutes, endpoints, interval, status_code, response_time, header, group, alerts
        )

    if include_ingress:
        ingresses = get_ingresses(kubeconfig, context)
        process_ingresses(
            ingresses, endpoints, interval, status_code, response_time, header, group, alerts
        )

    try:
        # Validate endpoints before writing to file
        validate_unique_names(endpoints)
    except click.ClickException as e:
        # ClickException will be caught by Click and displayed appropriately
        raise

    # Create the final output
    output_data = {"endpoints": endpoints}

    # Write to the output file
    with open(output, "w") as f:
        # Configure YAML dumper to prevent aliases
        yaml.Dumper.ignore_aliases = lambda *args: True
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
