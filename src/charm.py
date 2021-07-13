#!/usr/bin/env python3
# Copyright 2021 alex litvinov
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging
from jinja2 import Environment, FileSystemLoader

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus

from charms.nginx_ingress_integrator.v0.ingress import IngressRequires

logger = logging.getLogger(__name__)


class CharmNatsK8SCharm(CharmBase):

    __PEBBLE_SERVICE_NAME = 'nats'
    __ADDR_CLUSTER_REL_DATA_KEY = 'ingress-address'

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._template_env = None

        self.framework.observe(self.on.nats_pebble_ready, self._on_nats_pebble_ready)

        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_joined,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_departed,
                               self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_changed,
                               self._on_config_changed)

        ingress_config = {"service-hostname": self.config["external_hostname"], "service-name": self.app.name,
                          "service-port": self.config["client_port"]}

        logger.debug("Setting up ingress with env: {}".format(ingress_config))

        self.ingress = IngressRequires(self, ingress_config)

    def _on_nats_pebble_ready(self, event):

        container = event.workload

        cluster_relation = self.model.get_relation('cluster')
        all_unit_addresses = self._get_all_unit_addresses(
            cluster_relation)

        self.__update_nats_config(container, all_unit_addresses)

        layer = self.nats_layer()
        services = container.get_plan().to_dict().get("services", {})

        if services != layer["services"]:
            logging.info("Trying to add layer")
            container.add_layer("nats", layer, combine=True)
            logging.info("Added updated layer 'nats' to Pebble plan")

        # Autostart any services that were defined with startup: enabled
        container.autostart()

        self.ingress.update_config({"service-hostname": self.config["external_hostname"]})

        self.unit.status = ActiveStatus()

    def _on_config_changed(self, _):

        """Adapt Nats config to Juju changes"""
        logging.debug('Handling Juju config change')

        cluster_relation = self.model.get_relation('cluster')
        # try?
        my_address = self._get_my_address(cluster_relation)
        self._share_address_with_peers(my_address, cluster_relation)

        all_unit_addresses = self._get_all_unit_addresses(
            cluster_relation)

        container = self.unit.get_container('nats')
        self.__update_nats_config(container, all_unit_addresses)

        self.__restart_nats(container)

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
                    "command": "nats-server --config /etc/nats/nats-server.conf",
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
        :returns: This unit's  address.
        :rtype: str
        """
        network = self.model.get_binding(relation).network
        return str(network.bind_address)

    def _get_all_unit_addresses(self, relation):
        """Get all addresses shared by all peers over the relation.

        Including the current unit.

        :param relation: the peer relation
        :type relation: ops.model.Relation
        :returns: Each unit's
         address.
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

        logging.debug('All unit addresses: {}'.format(
            ', '.join(result)))

        return list(result)

    def __update_nats_config(self, workload_container, all_unit_addresses):
        """Write NATS conf file to disk.

        :param workload_container: the container in which NATS is running
        :type workload_container: ops.model.Container
        :param all_unit_addresses: Each unit's address.
        :type all_unit_addresses: List[str]
        """

        config_file_path = '/etc/nats/nats-server.conf'

        cluster_port = self.config['cluster_port']
        client_port = self.config['client_port']
        monitor_port = self.config['monitor_port']
        user = self.config['user']
        sys_user = self.config['system_user']
        password = self.config['password']
        sys_password = self.config['system_password']

        routes_with_ports = [s + ":" + str(cluster_port) for s in all_unit_addresses]
        routes_with_proto = ["nats://" + r for r in routes_with_ports]

        routes_prepared = ",".join(routes_with_proto)

        logging.debug('Writing config to {}'.format(config_file_path))

        self._push_template(workload_container, 'nats-server.conf', config_file_path,
                            {'cluster_port': cluster_port, 'client_port': client_port,
                             'monitor_port': monitor_port, 'routes': routes_prepared,
                             'user': user, 'password': password, "sys_user": sys_user,
                             "sys_pass": sys_password})

    def __restart_nats(self, workload_container):
        """Restart NATS by restarting the Pebble services.

        :param workload_container: the container in which NATS is running
        :type workload_container: ops.model.Container
        """
        services = workload_container.get_plan().to_dict().get('services', {})
        if not len(services):
            # No Pebble service defined yet, too early:
            return

        logging.info('Restarting NATS...')
        workload_container.stop(self.__PEBBLE_SERVICE_NAME)
        # Autostart any services that were defined with startup: enabled :
        workload_container.autostart()

    def _push_template(self, container, template_name, target_path, context={}):
        if self._template_env is None:
            self._template_env = Environment(loader=FileSystemLoader(
                f'{self.charm_dir}/templates'))
        container.push(
            target_path,
            self._template_env.get_template(template_name).render(**context),
            make_dirs=True
        )

    def _share_address_with_peers(self, my_address, relation):
        """Share this unit's address with peer units.
        :param relation: the peer relation
        :type relation: ops.model.Relation
        """
        relation.data[self.unit][self.__ADDR_CLUSTER_REL_DATA_KEY] = (
            my_address)


if __name__ == "__main__":
    main(CharmNatsK8SCharm)
