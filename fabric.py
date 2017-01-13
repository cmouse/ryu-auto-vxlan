# Copyright (c) 2017 Aki Tuomi <cmouse@cmouse.fi>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Contains code from Nippon Telegraph and Telephone Corporation.

import json
import uuid

from ryu.base import app_manager
from ryu.services.protocols.ovsdb import api as ovsdb
from ryu.services.protocols.ovsdb import event as ovsdb_event
from ryu.app.ofctl import api as ofctl_api
from ryu.lib.ovs import bridge as ovs_bridge
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, HANDSHAKE_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from webob import Response
from ryu.lib import dpid as dpid_lib
from ryu import cfg
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.app import simple_switch_13

OVSDB_PORT = 6640
MY_IP = "10.1.10.169"

class FabricManager(simple_switch_13.SimpleSwitch13):
  def __init__(self, *args, **kwargs):
    super(FabricManager, self).__init__(*args, **kwargs)
    self.switches = {}
    self.ovs = {}

  @set_ev_cls(ofp_event.EventOFPHello, HANDSHAKE_DISPATCHER)
  def register_switch(self, ev):
    dpid = ev.msg.datapath.id
    src = ev.msg.datapath.address[0]
    self.switches[src] = ev.msg.datapath

  @set_ev_cls(ofp_event.EventOFPStateChange, DEAD_DISPATCHER)
  def remove_switch(self, ev):
    dpid = ev.datapath.id
    src = ev.datapath.address[0]
    if src == "127.0.0.1":
      self.delete_all_pairs(dpid)
    else:
      master_dpid = self.switches.get("127.0.0.1", None)
      if master_dpid:
        self._del_vxlan_port(master_dpid.id, src, "0")
    del self.switches[src]
    del self.ovs[dpid]

  def delete_all_pairs(self, master_dpid):
    for ip, datapath in self.switches.iteritems():
      if ip != "127.0.0.1" and dpid:
        self._del_vxlan_port(dpid.id, MY_IP, "0")

  @set_ev_cls(ofp_event.EventOFPStateChange, MAIN_DISPATCHER)
  def config_switch(self, ev):
    dpid = ev.datapath.id
    src = ev.datapath.address[0]
    self._get_ovs_bridge(dpid)
    if src == "127.0.0.1":
      self.setup_all_pairs(dpid)
      return
    self.setup_vxlan_pair(dpid, src)
  
  def setup_all_pairs(self, master_dpid):
    for ip, datapath in self.switches.iteritems():
      if ip != "127.0.0.1" and dpid:
        self.logger.info("Setting up %s", ip, datapath.id)
        self.setup_vxlan_pair(datapath.id, ip)

  def setup_vxlan_pair(self, dpid, ip):
   master_dpid = self.switches.get("127.0.0.1", None)

   if not master_dpid:
     return

   master_dpid = self.switches["127.0.0.1"].id

   if not self._get_vxlan_port(dpid, MY_IP, "0"):
     self._add_vxlan_port(dpid, MY_IP, "0")

   if not self._get_vxlan_port(master_dpid, ip, "0"):
     self._add_vxlan_port(master_dpid, ip, "0")

  def _get_datapath(self, dpid):
    return ofctl_api.get_datapath(self, dpid)

  # Utility methods related to OVSDB
  def _get_ovs_bridge(self, dpid):
    datapath = self._get_datapath(dpid)
    if datapath is None:
        self.logger.debug('No such datapath: %s', dpid)
        return None

    ovs = self.ovs.get(dpid, None)
    ovsdb_addr = 'tcp:%s:%d' % (datapath.address[0], OVSDB_PORT)

    if (ovs is not None
        and ovs.datapath_id == dpid
        and ovs.vsctl.remote == ovsdb_addr):
      return ovs

    self.logger.info("Connecting to %s", ovsdb_addr)

    try:
      ovs = ovs_bridge.OVSBridge(
          CONF=self.CONF,
          datapath_id=datapath.id,
          ovsdb_addr=ovsdb_addr)
      ovs.init()
      self.ovs[dpid] = ovs
      return ovs
    except Exception as e:
      self.logger.exception('Cannot initiate OVSDB connection: %s', e)
      return None

  def _get_ofport(self, dpid, port_name):
    ovs = self._get_ovs_bridge(dpid)
    if ovs is None:
      return None

    try:
      return ovs.get_ofport(port_name)
    except Exception as e:
      self.logger.debug('Cannot get port number for %s: %s',
                        port_name, e)
      return None

  def _get_vxlan_port(self, dpid, remote_ip, key):
    # Searches VXLAN port named 'vxlan_<remote_ip>_<key>'
    return self._get_ofport(dpid, 'vxlan_%s_%s' % (remote_ip, key))

  def _add_vxlan_port(self, dpid, remote_ip, key):
    # If VXLAN port already exists, returns OFPort number
    vxlan_port = self._get_vxlan_port(dpid, remote_ip, key)
    if vxlan_port is not None:
      return vxlan_port

    ovs = self._get_ovs_bridge(dpid)
    if ovs is None:
      return None

    # Adds VXLAN port named 'vxlan_<remote_ip>_<key>'
    ovs.add_vxlan_port(
      name='vxlan_%s_%s' % (remote_ip, key),
      remote_ip=remote_ip,
      key=key)

    # Returns VXLAN port number
    return self._get_vxlan_port(dpid, remote_ip, key)

  def _del_vxlan_port(self, dpid, remote_ip, key):
    ovs = self._get_ovs_bridge(dpid)
    if ovs is None:
      return None

    # If VXLAN port does not exist, returns None
    vxlan_port = self._get_vxlan_port(dpid, remote_ip, key)
    if vxlan_port is None:
      return None

    # Deletes VXLAN port named 'vxlan_<remote_ip>_<key>'
    ovs.del_port('vxlan_%s_%s' % (remote_ip, key))

    # Returns deleted VXLAN port number
    return vxlan_port
