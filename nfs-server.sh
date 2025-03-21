#!/bin/sh
#
# Setup an NFS server on /nfs with support for external access from other experiments
#
# This script is derived from Jonathan Ellithorpe's Cloudlab profile at
# https://github.com/jdellithorpe/cloudlab-generic-profile. Thanks!
#

# Process command-line arguments
EXTERNAL_ACCESS="no"
ALLOWED_NETWORKS="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"

for arg in "$@"; do
  case $arg in
    --external-access=*)
      EXTERNAL_ACCESS="${arg#*=}"
      shift
      ;;
    --allowed-networks=*)
      ALLOWED_NETWORKS="${arg#*=}"
      shift
      ;;
    *)
      # Unknown option
      ;;
  esac
done

. /etc/emulab/paths.sh

OS=$(uname -s)
HOSTNAME=$(hostname -s)

#
# The storage partition is mounted on /nfs, if you change this, you
# must change profile.py also.
#
NFSDIR="/nfs"

#
# The name of the nfs network. If you change this, you must change
# profile.py also.
#
NFSNETNAME="nfsLan"

#
# The name of the "prepare" for image snapshot hook.
#
HOOKNAME="$BINDIR/prepare.pre.d/nfs-server.sh"

if ! (grep -q $HOSTNAME-$NFSNETNAME /etc/hosts); then
    echo "$HOSTNAME-$NFSNETNAME is not in /etc/hosts"
    exit 1
fi

#
# On Linux, see if the packages are installed
#
if [ "$OS" = "Linux" ]; then
    # === Software dependencies that need to be installed. ===
    apt-get update
    stat=`dpkg-query -W -f '${DB:Status-Status}\n' nfs-kernel-server`
    if [ "$stat" = "not-installed" ]; then
        echo ""
        echo "Installing NFS packages"
        apt-get --assume-yes install nfs-kernel-server nfs-common
        # Install firewall for external access
        if [ "$EXTERNAL_ACCESS" = "yes" ]; then
            apt-get --assume-yes install ufw
        fi
        # make sure the server is not running til we fix up exports
        service nfs-kernel-server stop
    fi
fi

# Get internal NFS network information
NFSIP=`grep -i $HOSTNAME-$NFSNETNAME /etc/hosts | awk '{print $1}'`
NFSNET=`echo $NFSIP | awk -F. '{printf "%s.%s.%s.0", $1, $2, $3}'`

# Get public/external IP if external access is enabled
PUBLIC_IP=""
if [ "$EXTERNAL_ACCESS" = "yes" ]; then
    if [ "$OS" = "Linux" ]; then
        # Get the public interface (usually eth0 or ens3)
        PUBLIC_IFACE=$(ip -o -4 route show to default | awk '{print $5}')
        PUBLIC_IP=$(ip -o -4 addr show dev $PUBLIC_IFACE | awk '{print $4}' | cut -d/ -f1)
    else
        # FreeBSD - get public IP
        PUBLIC_IP=$(ifconfig | grep -B1 "inet " | grep -v "inet 127" | grep -v "inet $NFSIP" | awk '$1=="inet" {print $2}' | head -n1)
    fi
    
    if [ -z "$PUBLIC_IP" ]; then
        echo "Warning: Could not determine public IP address, external access may not work"
    else
        echo "Public IP address for external access: $PUBLIC_IP"
    fi
fi

#
# If exports entry already exists, no need to do anything. 
#
if ! grep -q "^$NFSDIR" /etc/exports; then
    # Will be owned by root/wheel, you will have to use sudo on the clients
    # to make sub directories and protect them accordingly.
    mkdir -p -m 755 $NFSDIR

    echo ""
    echo "Setting up NFS exports"

    if [ "$OS" = "Linux" ]; then
        # Internal access
        echo "$NFSDIR $NFSNET/24(rw,sync,no_root_squash,no_subtree_check,fsid=0)" > /etc/exports
        
        # Add external access if enabled
        if [ "$EXTERNAL_ACCESS" = "yes" ]; then
            # For each allowed network, add to exports
            for network in $ALLOWED_NETWORKS; do
                echo "$NFSDIR $network(rw,sync,no_subtree_check)" >> /etc/exports
            done
        fi
    else
        # FreeBSD exports
        echo "$NFSDIR -network $NFSNET -mask 255.255.255.0 -maproot=root -alldirs" > /etc/exports
        
        # Add external access if enabled
        if [ "$EXTERNAL_ACCESS" = "yes" ]; then
            for network in $ALLOWED_NETWORKS; do
                NETADDR=$(echo $network | cut -d/ -f1)
                NETMASK=$(cdr2mask $(echo $network | cut -d/ -f2))
                echo "$NFSDIR -network $NETADDR -mask $NETMASK -maproot=root -alldirs" >> /etc/exports
            done
        fi
    fi

    if [ "$OS" = "Linux" ]; then
        # For internal access only
        if [ "$EXTERNAL_ACCESS" = "no" ]; then
            # Make sure we start RPCbind to listen on the right interfaces.
            echo "OPTIONS=\"-l -h 127.0.0.1 -h $NFSIP\"" > /etc/default/rpcbind
        else
            # For external access, listen on all interfaces
            echo "OPTIONS=\"-l\"" > /etc/default/rpcbind
        fi

        # We want to allow rpcinfo to operate from the clients.
        sed -i.bak -e "s/^rpcbind/#rpcbind/" /etc/hosts.deny
    else
        # On FreeBSD we will start all the services manually
        # But make sure the options are correct
        cp -p /etc/rc.conf /etc/rc.conf.bak
        
        if [ "$EXTERNAL_ACCESS" = "no" ]; then
            # Internal access only
            cat <<EOF >> /etc/rc.conf
rpcbind_enable="NO"
rpcbind_flags="-h $NFSIP"
rpc_lockd_enable="NO"
rpc_lockd_flags="-h $NFSIP"
rpc_statd_enable="NO"
rpc_statd_flags="-h $NFSIP"
mountd_enable="NO"
mountd_flags="-h $NFSIP"
nfs_server_enable="NO"
nfs_server_flags="-u -t -h $NFSIP"
nfs_reserved_port_only="YES"
EOF
        else
            # External access - listen on all interfaces
            cat <<EOF >> /etc/rc.conf
rpcbind_enable="NO"
rpc_lockd_enable="NO"
rpc_statd_enable="NO"
mountd_enable="NO"
nfs_server_enable="NO"
nfs_server_flags="-u -t"
nfs_reserved_port_only="YES"
EOF
        fi
    fi
fi

# Define CIDR to netmask conversion function for FreeBSD
cdr2mask() {
    # Number of args to shift, 255..255, first non-255 byte, zeroes
    set -- $(( 5 - ($1 / 8) )) 255 255 255 255 $(( (255 << (8 - ($1 % 8))) & 255 )) 0 0 0
    [ $1 -gt 1 ] && shift $1 || shift
    echo ${1-0}.${2-0}.${3-0}.${4-0}
}

#
# Create prepare hook to remove our customizations before we take the
# image snapshot. They will get reinstalled at reboot after image snapshot.
# Remove the hook script too, we do not want it in the new image, and
# it will get recreated as well at reboot. 
#
if [ ! -e $HOOKNAME ]; then
    if [ "$OS" = "Linux" ]; then
        cat <<EOFL > $HOOKNAME
sed -i.bak -e '/^\\$NFSDIR/d' /etc/exports
sed -i.bak -e "s/^#rpcbind/rpcbind/" /etc/hosts.deny
echo "OPTIONS=\"-l -h 127.0.0.1\"" > /etc/default/rpcbind
rm -f $HOOKNAME
exit 0
EOFL
    else
        cat <<EOFB > $HOOKNAME
sed -i.bak -e '/^\\$NFSDIR/d' /etc/exports
# stopping services when making a snapshot might not be a
# good idea; i.e., if one of the services hangs
/etc/rc.d/lockd onestop
/etc/rc.d/statd onestop
/etc/rc.d/nfsd onestop
/etc/rc.d/mountd onestop
/etc/rc.d/rpcbind onestop
cp -p /etc/rc.conf.bak /etc/rc.conf
rm -f $HOOKNAME
exit 0
EOFB
    fi
fi
chmod +x $HOOKNAME

echo ""

if [ "$OS" = "Linux" ]; then
    echo "Restarting rpcbind"
    service rpcbind stop
    sleep 1
    service rpcbind start
    sleep 1
fi

echo "Starting NFS services"
if [ "$OS" = "Linux" ]; then
    service nfs-kernel-server start
    
    # Configure firewall if external access is enabled
    if [ "$EXTERNAL_ACCESS" = "yes" ]; then
        echo "Configuring firewall for external NFS access"
        # Reset UFW to default
        ufw --force reset
        
        # Allow NFS-related ports
        ufw allow ssh
        ufw allow nfs
        ufw allow 111/tcp
        ufw allow 111/udp
        ufw allow 2049/tcp
        ufw allow 2049/udp
        ufw allow 32765:32769/tcp
        ufw allow 32765:32769/udp
        
        # Enable firewall
        ufw --force enable
    fi
else
    # nfsd starts rpcbind and mountd
    /etc/rc.d/nfsd onestart
    /etc/rc.d/statd onestart
    /etc/rc.d/lockd onestart
    
    # For FreeBSD, configure firewall if needed
    if [ "$EXTERNAL_ACCESS" = "yes" ]; then
        echo "Note: Manual firewall configuration may be needed for FreeBSD"
    fi
fi

# Give it time to start-up
sleep 5

if [ "$EXTERNAL_ACCESS" = "yes" ]; then
    echo ""
    echo "======================= EXTERNAL ACCESS INFO ========================"
    echo "NFS server is configured for external access!"
    echo "To mount from another experiment, use:"
    echo "  sudo mount -t nfs $PUBLIC_IP:$NFSDIR /mnt"
    echo "===================================================================="
fi