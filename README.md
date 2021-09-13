# charm-nats-server-k8s

## Description

An operator, that manages the lifecycle of NATS Core Server.

NATS is an open-source, cloud-native, high-performance messaging system.

https://docs.nats.io/nats-concepts/intro

## Usage

The `charm-nats-server-k8s` charm deploys NATS Core Server  on top of Kubernetes:


    juju deploy --resource 
    nats-image=nats:2.1.7-alpine3.11
        charm-nats-server-k8s

### Adding New Units and Scaling

Charm supports running multiple units of NATS Server and applying the necessary configuration
to all of the running units.

To add a unit to a deployed application use:

    juju add-unit charm-nats-server-k8s

To scale the application to have a particular number of units use:

    juju scale-application charm-nats-server-k8s 3

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
