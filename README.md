python-ryu application for automated VxLAN
==========================================

Experimental script for automatically creating vxlan pairs between
virtual switches. Assumed topology is hub-spoke.

Please read the script before using.

This script does not work without modifying ryu code.

Debian jessie instructions for spokes
-------------------------------------
```
allow-ovs ovsbr0
iface ovsbr0 inet dhcp
  ovs_type OVSBridge
  ovs_extra set-controller ovsbr0 tcp:10.1.10.2:6633
  pre-up ovs-vsctl set-manager ptcp:6640
  mtu 1280
  up ip route add 10.117.0.0/16 via 10.117.9.1 dev ovsbr0 
  down ip route del 10.117.0.0/16 via 10.117.9.1 dev ovsbr0
```