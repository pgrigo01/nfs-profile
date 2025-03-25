# Import the Portal object.
import geni.portal as portal
# Import the ProtoGENI library.
import geni.rspec.pg as pg
# Import the InstaGENI library.
import geni.rspec.igext as ig
# Import the Emulab specific extensions.
import geni.rspec.emulab as emulab

# Create a portal object,
pc = portal.Context()

agglist = [
    ("urn:publicid:IDN+emulab.net+authority+cm", "emulab.net"),
    ("urn:publicid:IDN+utah.cloudlab.us+authority+cm", "utah.cloudlab.us"),
    ("urn:publicid:IDN+clemson.cloudlab.us+authority+cm", "clemson.cloudlab.us"),
    ("urn:publicid:IDN+wisc.cloudlab.us+authority+cm", "wisc.cloudlab.us"),
    ("urn:publicid:IDN+apt.emulab.net+authority+cm", "apt.emulab.net"),
    ("", "Any")
]

imagelist = [
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU24-64-STD', 'UBUNTU 24.04'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD', 'UBUNTU 22.04'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD', 'UBUNTU 20.04'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//CENTOS7-64-STD', 'CENTOS 7'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//FBSD113-64-STD', 'FreeBSD 11.3')
]

# Define node count parameter
pc.defineParameter(
    "node_count", "Number of Nodes",
    portal.ParameterType.INTEGER,
    1,  # Default to 1 node
    longDescription="Number of nodes to create (1-10)")

pc.defineParameter(
    "aggregate", "Specific Aggregate",
    portal.ParameterType.STRING,
    agglist[0][0], agglist)

pc.defineParameter(
    "image", "Node Image",
    portal.ParameterType.IMAGE,
    imagelist[0][0],
    imagelist,
    longDescription="The image your nodes will run.")

pc.defineParameter(
    "routableIP", "Routable IP",
    portal.ParameterType.BOOLEAN, False,
    longDescription="Add a routable IP to each VM.")

pc.defineParameter(
    "extra_disk_space", "Extra Disk Space (GB)",
    portal.ParameterType.INTEGER, 0,
    longDescription="The size of storage to mount at /mydata. 0 means no extra storage.")

# New parameters for external shared NFS mount (persistent across experiments)
pc.defineParameter(
    "nfs_server", "NFS Server",
    portal.ParameterType.STRING, "nfssrv.example.com",
    longDescription="The NFS server that hosts the shared /mydata directory.")

pc.defineParameter(
    "nfs_export", "NFS Export Path",
    portal.ParameterType.STRING, "/users/pgrigo01/nfsshare",
    longDescription="The exported path on the NFS server.")

pc.defineStructParameter(
    "sharedVlans", "Add Shared VLAN", [],
    multiValue=True, itemDefaultValue={}, min=0, max=None,
    members=[
        portal.Parameter(
            "createSharedVlan", "Create Shared VLAN",
            portal.ParameterType.BOOLEAN, False,
            longDescription="Create a new shared VLAN with the name above."),
        portal.Parameter(
            "connectSharedVlan", "Connect to Shared VLAN",
            portal.ParameterType.BOOLEAN, False,
            longDescription="Connect an existing shared VLAN with the name below."),
        portal.Parameter(
            "name", "Shared VLAN Name",
            portal.ParameterType.STRING, "",
            longDescription="Shared VLAN name (must be fewer than 32 alphanumeric characters)."),
        portal.Parameter(
            "ip_address", "Shared VLAN IP Address",
            portal.ParameterType.STRING, "10.254.254.1",
            longDescription="IP address for the shared VLAN interface."),
        portal.Parameter(
            "subnet_mask", "Shared VLAN Netmask",
            portal.ParameterType.STRING, "255.255.255.0",
            longDescription="Subnet mask for the shared VLAN interface.")
    ])

params = pc.bindParameters()

# Parameter validation
if params.node_count < 1 or params.node_count > 10:
    pc.reportError(portal.ParameterError("Invalid number of nodes (must be between 1 and 10)"))

i = 0
for x in params.sharedVlans:
    n = 0
    if x.createSharedVlan:
        n += 1
    if x.connectSharedVlan:
        n += 1
    if n > 1:
        err = portal.ParameterError(
            "Must choose only a single shared vlan operation (create, connect)",
            ['sharedVlans[%d].createSharedVlan' % (i,),
             'sharedVlans[%d].connectSharedVlan' % (i,)])
        pc.reportError(err)
    if n == 0:
        err = portal.ParameterError(
            "Must choose one of the shared vlan operations: create, connect",
            ['sharedVlans[%d].createSharedVlan' % (i,),
             'sharedVlans[%d].connectSharedVlan' % (i,)])
        pc.reportError(err)
    i += 1

pc.verifyParameters()

# Create a Request object
request = pc.makeRequestRSpec()

tour = ig.Tour()
tour.Description(ig.Tour.TEXT, 
    "Create %d VM(s) with optional storage and VLAN connectivity." % params.node_count)
request.addTour(tour)

# Create multiple nodes
nodes = []
sharedvlans = []

for i in range(params.node_count):
    node = ig.XenVM("node-%d" % i)
    node.disk_image = params.image
    node.exclusive = False

    if params.extra_disk_space > 0:
        # Attach a blockstore at /mydata if extra storage is requested
        bs = node.Blockstore("bs-%d" % i, "/mydata")
        bs.size = str(params.extra_disk_space) + "GB"
        bs.placement = "any"
        
        # Add startup script for blockstore initialization
        node.addService(pg.Execute(shell="sh", command="""
            sudo mkdir -p /mydata
            sudo chmod 777 /mydata
            echo "Dataset ready for population at /mydata" > /mydata/README.txt
            echo "[$(date)] Storage setup complete" >> /var/log/storage-setup.log
        """))
    else:
        # No extra disk; mount the external shared NFS so storage persists across experiments
        node.addService(pg.Execute(shell="sh", command=f"""
            sudo mkdir -p /mydata
            sudo mount -t nfs {params.nfs_server}:{params.nfs_export} /mydata
            sudo chmod 777 /mydata
            echo "Shared NFS mounted at /mydata" >> /var/log/shared-nfs-setup.log
        """))
    
    if params.routableIP:
        node.routable_control_ip = True
    if params.aggregate:
        node.component_manager_id = params.aggregate

    # Configure VLANs for each node
    k = 0
    for x in params.sharedVlans:
        iface = node.addInterface("ifSharedVlan%d" % (k,))
        if x.ip_address:
            # Increment last octet of IP for each node
            ip_parts = x.ip_address.split('.')
            ip_parts[3] = str(int(ip_parts[3]) + i)
            node_ip = '.'.join(ip_parts)
            iface.addAddress(pg.IPv4Address(node_ip, x.subnet_mask))
        
        # Only create/connect VLAN once (on first node)
        if i == 0:
            sharedvlan = pg.Link('shared-vlan-%d' % (k,))
            sharedvlan.addInterface(iface)
            if x.createSharedVlan:
                sharedvlan.createSharedVlan(x.name)
            else:
                sharedvlan.connectSharedVlan(x.name)
            sharedvlan.link_multiplexing = True
            sharedvlan.best_effort = True
            sharedvlans.append(sharedvlan)
        else:
            # Add interfaces of other nodes to existing VLANs
            sharedvlans[k].addInterface(iface)
        k += 1

    nodes.append(node)
    request.addResource(node)

for sv in sharedvlans:
    request.addResource(sv)

pc.printRequestRSpec(request)
