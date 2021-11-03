# nats-server-operator

## Description

An operator, that manages the lifecycle of NATS Core Server.

NATS is an open-source, cloud-native, high-performance messaging system.

https://docs.nats.io/nats-concepts/intro

## Usage

The `nats-server-operator` charm deploys NATS Core Server  on top of Kubernetes:


    juju deploy --resource nats-image=nats:2.1.7-alpine3.11 nats-server-operator

### Adding New Units and Scaling

Charm supports running multiple units of NATS Server and applying the necessary configuration
to all of the running units.

To add a unit to a deployed application use:

    juju add-unit nats-server-operator

To scale the application to have a particular number of units use:

    juju scale-application nats-server-operator 3

### Adding New Units and Scaling

Charm supports running NATS Server with simple TLS scenario by manually specifying tls_cert and tls_key
Configure tls_cert and tls_key parameters with juju

    juju config nats-server-operator tls_key="$(cat nats-server-tls.key)"
    
    juju config nats-server-operator tls_cert="$(cat nats-server-cert.crt)"

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
    
## Roadmap to completion

What is needed before this charm could be considered complete
and production ready:

1. Add tests with pytest-operator for maintainability
2. Add TLS scenario through relation with easyrsa
