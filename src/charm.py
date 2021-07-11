#!/usr/bin/env python3
# Copyright 2021 alex litvinov
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging
from configparser import ConfigParser

from ops.charm import CharmBase
from ops.pebble import ChangeError
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, ModelError, MaintenanceStatus, BlockedStatus, WaitingStatus
from oci_image import OCIImageResource, OCIImageResourceError
#from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
#from ops.pebble import Layer, ConnectionError

logger = logging.getLogger(__name__)


class CharmNatsK8SCharm(CharmBase):

    __PEBBLE_SERVICE_NAME = 'nats'
    __ADDR_CLUSTER_REL_DATA_KEY = 'ingress-address'

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.nats_pebble_ready, self._on_nats_pebble_ready)

        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_joined,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_departed,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_changed,
                               self._on_config_changed)

        self.__START_NATS_CMD = f'nats-server -D -p={self.config["client_port"]} -m={self.config["monitor_port"]} ' \
                                f'--cluster=nats://0.0.0.0:{self.config["cluster_port"]}'

        ingress_config = {"service-hostname": self.config["external_hostname"], "service-name": self.app.name,
                                              "service-port": self.config["client_port"]}

        logger.debug("Setting up ingress with env: {}".format(ingress_config))

        self.ingress = IngressRequires(self, ingress_config)

        self._stored.set_default(things=[])

    def _on_nats_pebble_ready(self, event):

        container = event.workload

        cluster_relation = self.model.get_relation('cluster')
        my_address = self._get_my_address(cluster_relation)
        all_unit_addresses = self._get_all_unit_addresses(
            cluster_relation)

        layer = self.nats_layer()
        services = container.get_plan().to_dict().get("services", {})

        if services != layer["services"]:
            logging.info("Trying to add layer")
            container.add_layer("nats", layer, combine=True)
            logging.info("Added updated layer 'nats' to Pebble plan")

        is_running = container.get_service('nats').is_running()
        if is_running:
            container.stop("nats")

        # Autostart any services that were defined with startup: enabled
        container.autostart()

        self.ingress.update_config({"service-hostname": self.config["external_hostname"]})

        self.unit.status = ActiveStatus()

    def _on_config_changed(self, _):

        """Adapt Nats config to Juju changes"""
        logging.debug('Handling Juju config change')

        # layer = self.nats_layer()

        cluster_relation = self.model.get_relation('cluster')

        my_address = self._get_my_address(cluster_relation)
        print(" ADDR =")
        print(my_address)
        self._share_address_with_peers(my_address, cluster_relation)

        all_unit_addresses = self._get_all_unit_addresses(
            cluster_relation)
        print("all ADDR =")
        print(all_unit_addresses)

        self.container = self.unit.get_container('nats')

        try:
            is_running = self.container.get_service('nats').is_running()
            if is_running:
                self.container.stop("nats")
        except ModelError as exc:
            pass

        #if self.container.get_service("nats").is_running():
        #    self.container.stop("nats")

        #try:
        #    self.run_cmd('nats-server --signal stop', "stop")
        #except ChangeError:
        #    logging.info("NATS server already stopped")

        routes_with_ports = [s + ":" + str(self.config["cluster_port"]) for s in all_unit_addresses]
        self.run_cmd(f'{self.__START_NATS_CMD} --routes={",".join(routes_with_ports)}', "nats")

        logging.info("Restarted NATS service")

    def nats_layer(self) -> dict:
        """Generate Pebble Layer for Nats"""

        return {
            "summary": "nats layer",
            "description": "pebble config layer for nats",
            "services": {
                self.__PEBBLE_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Nats server",
                    "command": self.__START_NATS_CMD,
                    "startup": "enabled",
                    "environment": {"KUBERNETES_POD_NAMESPACE": self.model.name,
                                    "NATS_SERVER": self.config["nats_version"]},
                }
            }
        }

    def _get_my_address(self, relation):
        """Returns this unit's address on which it wishes to be contacted.

        :param relation: the peer relation. See
                         https://github.com/canonical/operator/issues/534
        :type relation: ops.model.Relation
        :returns: This unit's (first) ingress address.
        :rtype: str
        """
        network = self.model.get_binding(relation).network
        return str(network.bind_address)

    def _get_all_unit_addresses(self, relation):
        """Get all ingress addresses shared by all peers over the relation.

        Including the current unit.

        :param relation: the peer relation
        :type relation: ops.model.Relation
        :returns: Each unit's (first) ingress address.
        :rtype: List[str]
        """
        result = set()

        my_address = self._get_my_address(relation)
        if my_address is not None:
            result.add(my_address)

        for unit in relation.units:
            try:
                unit_address = relation.data[unit][
                    self.__ADDR_CLUSTER_REL_DATA_KEY]
            except KeyError:
                # This unit hasn't shared its address yet. It's OK as there will
                # be other hook executions later calling this again:
                continue
            if unit_address is not None:
                result.add(unit_address)

        logging.debug('All unit ingress addresses: {}'.format(
            ', '.join(result)))

        return list(result)

    def _share_address_with_peers(self, my_ingress_address, relation):
        """Share this unit's ingress address with peer units.

        :param relation: the peer relation
        :type relation: ops.model.Relation
        """
        relation.data[self.unit][self.__ADDR_CLUSTER_REL_DATA_KEY] = (
            my_ingress_address)

    def run_cmd(self, cmd, label="cmd", env=None):
        layer = {
            "services": {
                label: {
                    "override": "replace",
                    "startup": "disabled",
                    "command": cmd,
                    "environment": env or {},
                }
            }
        }
        logger.info("running cmd: %s", cmd)
        self.container.add_layer(label, layer, combine=True)

        try:
            self.container.start(label)
        except ChangeError as exc:
            #  Start service "cmd" (cannot start service: exited quickly with code 0)
            if "exited quickly with code 0" in exc.err:
                logger.info("cmd succeed")
                return True
            else:
                logger.exception("cmd failed")
                return False

if __name__ == "__main__":
    main(CharmNatsK8SCharm)
