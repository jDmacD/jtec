import click
import yaml
from kubernetes import client, config
from ..classes.endpoint import Endpoint


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
            self.fail(f"Header key cannot be empty", param, ctx)
        return (key, val)


HEADER_TYPE = HeaderParamType()


def get_ingresses(kubeconfig):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        try:
            config.load_kube_config()
        except:
            config.load_incluster_config()

    # Initialize the networking API client
    v1 = client.NetworkingV1Api()

    # Get all Ingresses from all namespaces
    ingresses = v1.list_ingress_for_all_namespaces()

    return ingresses


def process_ingresses(
    ingresses, endpoints, interval, status_code, response_time, header
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

                # Create endpoint name
                endpoint_name = (
                    f"{name}" if len(ingress.spec.rules) == 1 else f"{name}[{i+1}]"
                )

                endpoint = Endpoint(
                    name=endpoint_name,
                    url=url,
                    enabled=annotations.get("gatus.io/enabled", True),
                    group=namespace,
                    interval=annotations.get("gatus.io/interval", interval),
                    conditions=generate_conditions(
                        annotations, status_code, response_time
                    ),
                    headers=generate_headers(annotations, header),
                )
                endpoints.append(endpoint.to_dict())


def get_httproutes(kubeconfig):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        try:
            config.load_kube_config()
        except:
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
    httproutes, endpoints, interval, status_code, response_time, header
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

            # Create endpoint name using the HTTPRoute name
            # If there is more than one hostname they are numbered
            endpoint_name = name if len(hostnames) == 1 else f"{name}[{i+1}]"

            endpoint = Endpoint(
                name=endpoint_name,
                url=url,
                enabled=annotations.get("gatus.io/enabled", True),
                group=parent_ref_name,
                interval=annotations.get("gatus.io/interval", interval),
                conditions=generate_conditions(annotations, status_code, response_time),
                headers=generate_headers(annotations, header),
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


@click.command("gatus", short_help="creates gatus configuration")
@click.option(
    "--output",
    "-o",
    default="endpoints.yaml",
    help="Output YAML file",
    envvar="OUTPUT_FILE",
)
@click.option("--kubeconfig", help="Path to kubeconfig file", envvar="KUBECONFIG")
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
def main(
    output,
    kubeconfig,
    interval,
    status_code,
    response_time,
    header,
    include_ingress,
    include_httproute,
):
    endpoints = []

    if include_httproute:
        httproutes = get_httproutes(kubeconfig)
        process_httproutes(
            httproutes, endpoints, interval, status_code, response_time, header
        )

    if include_ingress:
        ingresses = get_ingresses(kubeconfig)
        process_ingresses(
            ingresses, endpoints, interval, status_code, response_time, header
        )

    # Create the final output
    output_data = {"endpoints": endpoints}

    # Write to the output file
    with open(output, "w") as f:
        # Configure YAML dumper to prevent aliases
        yaml.Dumper.ignore_aliases = lambda *args: True
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
