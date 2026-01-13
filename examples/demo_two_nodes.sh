#!/usr/bin/env bash
set -euo pipefail

# Demo: Two nodes with auto-sync on one machine
# Shows peer registration, group discovery, and automatic synchronization

echo "=== Learning Battery Market Demo ==="
echo ""

# Cleanup from previous runs
rm -rf ./nodeA ./nodeB 2>/dev/null || true

# 1) Initialize both nodes
echo "1. Initializing nodes..."
lb --data ./nodeA init
lb --data ./nodeB init
echo "   Nodes initialized."
echo ""

# 2) Create group on Node A
echo "2. Creating group on Node A..."
GID=$(lb --data ./nodeA create-group --name "demo-group")
echo "   Group ID: $GID"
echo ""

# 3) Get Node B's public key and add as member
echo "3. Adding Node B as a member..."
B_PUB=$(lb --data ./nodeB info | python3 -c 'import json,sys; print(json.load(sys.stdin)["sign_pub"])')
lb --data ./nodeA add-member --group "$GID" --pub "$B_PUB" --role member
echo "   Node B added to group."
echo ""

# 4) Publish some claims on Node A
echo "4. Publishing claims on Node A..."
lb --data ./nodeA publish-claim --group "$GID" --text "Capture compiler invocation exactly." --tags build,debug
lb --data ./nodeA publish-claim --group "$GID" --text "Use structured logging for production systems." --tags logging,production
lb --data ./nodeA publish-claim --group "$GID" --text "Always validate user inputs before processing." --tags security,validation
echo "   3 claims published."
echo ""

# 5) Start P2P server on Node A (in background)
echo "5. Starting P2P server on Node A (port 7337)..."
lb --data ./nodeA run-p2p --host 127.0.0.1 --port 7337 &
P2P_PID=$!
sleep 2  # Wait for server to start
echo "   P2P server running (PID: $P2P_PID)"
echo ""

# 6) Register Node A as a peer on Node B
echo "6. Registering peer on Node B..."
lb --data ./nodeB peer-add --host 127.0.0.1 --port 7337 --alias "nodeA"
echo "   Peer registered."
echo ""

# 7) Discover groups from Node A
echo "7. Discovering groups from Node A..."
lb --data ./nodeB discover-groups --host 127.0.0.1 --port 7337
echo ""

# 8) Subscribe to the group for auto-sync
echo "8. Subscribing to group for auto-sync (60 second interval)..."
lb --data ./nodeB subscribe --group "$GID" --host 127.0.0.1 --port 7337 --interval 60
echo "   Subscribed to group."
echo ""

# 9) List subscriptions
echo "9. Listing subscriptions on Node B..."
lb --data ./nodeB subscription-list
echo ""

# 10) Manual sync to get the data immediately
echo "10. Performing manual sync..."
lb --data ./nodeB sync-now --group "$GID" --host 127.0.0.1 --port 7337
echo "   Sync complete."
echo ""

# 11) Compile context on Node B (should now have the claims)
echo "11. Compiling context on Node B..."
lb --data ./nodeB compile-context --group "$GID" --query "debug build logging" --top-k 3
echo ""

# 12) List peers on Node B
echo "12. Listing peers on Node B..."
lb --data ./nodeB peer-list
echo ""

# Cleanup
echo "=== Demo Complete ==="
echo ""
echo "Stopping P2P server..."
kill $P2P_PID 2>/dev/null || true

echo ""
echo "To run the full auto-sync demo manually:"
echo ""
echo "  Terminal 1 (Node A - Server):"
echo "    lb --data ./nodeA run-p2p --host 0.0.0.0 --port 7337"
echo ""
echo "  Terminal 2 (Node B - Client with auto-sync):"
echo "    lb --data ./nodeB run-p2p --host 0.0.0.0 --port 7338"
echo "    # Sync daemon runs in background, syncing every 60 seconds"
echo ""
echo "  Disable auto-sync:"
echo "    lb --data ./nodeB run-p2p --port 7338 --no-sync"
echo ""
