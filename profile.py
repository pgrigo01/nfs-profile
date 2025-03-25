"""This profile sets up an NFS server that can be accessed from other experiments. The NFS server 
uses persistent storage that will remain available even after this experiment is terminated.

Instructions:
- The NFS server will have both an internal interface (for clients in this experiment) 
  and a public interface (for clients in other experiments)
- Your shared NFS directory is mounted at `/nfs` on all nodes
- To access from other experiments, use the public IP address of the NFS server
- The server hostname 'nfs' will be resolvable within CloudLab"""

# Import the Portal object.
import geni.portal as portal
# Import the ProtoGENI library.
import geni.rspec.pg as pg
# Import the Emulab specific extensions.
import geni.rspec.emulab as emulab

# Create a portal context.
pc = portal.Context()

# Create a Request object to start building the RSpec.
request = pc.makeRequestRSpec()

# Client image list
imageList = [
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD', 'UBUNTU 20.04'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD', 'UBUNTU 22.04'),
]

# Server image list, not tested with CentOS
imageList2 = [
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD', 'UBUNTU 20.04'),
    ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD', 'UBUNTU 22.04'),

]

# Do not change these unless you change the setup scripts too.
nfsServerName = "nfs"
nfsLanName    = "nfsLan"
nfsDirectory  = "/nfs"

# Number of NFS clients (there is always a server)
pc.defineParameter("clientCount", "Number of NFS clients",
                   portal.ParameterType.INTEGER, 2)

pc.defineParameter("osImage", "Select OS image for clients",
                   portal.ParameterType.IMAGE,
                   imageList[0], imageList)

pc.defineParameter("osServerImage", "Select OS image for server",
                   portal.ParameterType.IMAGE,
                   imageList2[0], imageList2)

pc.defineParameter("nfsSize", "Size of NFS Storage",
                   portal.ParameterType.STRING, "200GB",
                   longDescription="Size of disk partition to allocate on NFS server")

pc.defineParameter("usePersistentStorage", "Use persistent storage",
                   portal.ParameterType.BOOLEAN, True,
                   longDescription="Check to use persistent storage that will remain available after experiment termination")

pc.defineParameter("allowExternalAccess", "Allow external NFS access",
                   portal.ParameterType.BOOLEAN, True,
                   longDescription="Check to allow NFS access from other experiments")

pc.defineParameter("externalNetworks", "Networks allowed for external access",
                   portal.ParameterType.STRING, "10.0.0.0/8 172.16.0.0/12 192.168.0.0/16",
                   longDescription="Space-separated list of networks in CIDR notation allowed to access NFS")

# Always need this when using parameters
params = pc.bindParameters()

# The NFS network. All these options are required.
nfsLan = request.LAN(nfsLanName)
nfsLan.best_effort       = True
nfsLan.vlan_tagging      = True
nfsLan.link_multiplexing = True

# The NFS server.
nfsServer = request.RawPC(nfsServerName)
nfsServer.disk_image = params.osServerImage

# Add a public interface to the NFS server if external access is enabled
if params.allowExternalAccess:
    nfsServer.routable_control_ip = True

# Attach server to lan for internal access
nfsLan.addInterface(nfsServer.addInterface())

# Storage: either persistent or ephemeral depending on user choice
if params.usePersistentStorage:
    # Use a persistent dataset
    nfsBS = nfsServer.Blockstore("nfsBS", nfsDirectory)
    nfsBS.size = params.nfsSize
    nfsBS.persistent = True
else:
    # Use a temporary blockstore (original behavior)
    nfsBS = nfsServer.Blockstore("nfsBS", nfsDirectory)
    nfsBS.size = params.nfsSize

# Pass the external access parameters to the server setup script
nfsServerCmd = "sudo /bin/bash /local/repository/nfs-server.sh"
if params.allowExternalAccess:
    nfsServerCmd += " --external-access=yes --allowed-networks='" + params.externalNetworks + "'"

# Initialization script for the server
nfsServer.addService(pg.Execute(shell="sh", command=nfsServerCmd))

# The NFS clients, also attached to the NFS lan.
for i in range(1, params.clientCount+1):
    node = request.RawPC("node%d" % i)
    node.disk_image = params.osImage
    nfsLan.addInterface(node.addInterface())
    # Initialization script for the clients
    node.addService(pg.Execute(shell="sh", command="sudo /bin/bash /local/repository/nfs-client.sh"))
    pass

# Print the RSpec to the enclosing page.
pc.printRequestRSpec(request)