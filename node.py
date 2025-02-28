import hashlib
import socket
import threading
import json
import traceback
import time
import os
import sys
import signal


class ChordNode:
    def __init__(self, ip, port, bootstrap_ip=None, bootstrap_port=None):
        self.ip = ip
        self.port = port
        self.node_id = self.generate_id(ip, port)
        self.data_store = {}  # DHT key-value store
        self.predecessor = None

        if bootstrap_ip and bootstrap_port:
            # This is a new node joining an existing network
            print(f"[NODE {self.node_id}] Attempting to join network via {bootstrap_ip}:{bootstrap_port}")
            self.join(bootstrap_ip, bootstrap_port)
        else:
            # This is the bootstrap node
            self.successor = {"node_id": self.node_id, "ip": self.ip, "port": self.port}
            print(f"[BOOTSTRAP NODE] Initialized with self-successor: {self.successor}")

        # Start the server
        server_thread = threading.Thread(target=self.start_server)
        server_thread.start()

        # Capture Ctrl+C
        signal.signal(signal.SIGINT, self.signal_handler)

        print(f"[NODE {self.node_id}] Server running at {self.ip}:{self.port}. Press Ctrl+C to shut down.")
        while True:
            time.sleep(1)  # Keep the program alive

    
    def signal_handler(self, sig, frame):
        print("\n[NODE] Received Ctrl+C. Shutting down...")
        os._exit(0)
        

    def generate_id(self, ip, port):
        """ Δημιουργεί μοναδικό ID με SHA-1(ip:port) """
        node_str = f"{ip}:{port}".encode()
        return int(hashlib.sha1(node_str).hexdigest(), 16) % (2**160)

    def start_server(self):
        """ Ξεκινάει έναν TCP server για επικοινωνία με άλλους κόμβους """
        try:
            print(f"[DEBUG] Trying to start server on {self.ip}:{self.port}")  # Debugging
            print("[DEBUG] Creating socket...")
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            print("[DEBUG] Setting socket options...")
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            print(f"[DEBUG] Binding server to {self.ip}:{self.port}...")
            server.bind((self.ip, self.port))

            print("[DEBUG] Server is now listening...")
            server.listen(5)
            print(f"[NODE {self.node_id}] Listening on {self.ip}:{self.port}...")  # Αν εμφανιστεί, ο server τρέχει

            while True:
                conn, addr = server.accept()
                print(f"[NODE {self.node_id}] Connection from {addr}")  # Δείχνει αν υπάρχει εισερχόμενη σύνδεση
                threading.Thread(target=self.handle_request, args=(conn,)).start()
        except Exception as e:
            print(f"[ERROR] Server failed to start: {e}")
            traceback.print_exc()
        finally:
            server.close() #Σωστό κλείσιμο του socket


    def join(self, bootstrap_ip, bootstrap_port):
        """ Εισάγει τον κόμβο στον δακτύλιο Chord μέσω του bootstrap node """
        print(f"[NODE {self.node_id}] Attempting to join network via {bootstrap_ip}:{bootstrap_port}")

        try:
            # Συνδέεται στον bootstrap node για να βρει τον successor του
            request = {"command": "find_successor", "node_id": self.node_id}
            print(f"[DEBUG] Sending request to bootstrap node: {request}")

            successor_response = self.send_request(bootstrap_ip, bootstrap_port, request)

            print(f"[DEBUG] Response from bootstrap: {successor_response}")

            if successor_response["status"] == "success":
                self.successor = successor_response["successor"]
                print(f"[NODE {self.node_id}] Successor found: {self.successor}")

                # Ενημερώνει τον successor για τον νέο predecessor
                update_predecessor_request = {
                    "command": "update_predecessor",
                    "node_id": self.node_id,
                    "ip": self.ip,
                    "port": self.port
                }
                print(f"[DEBUG] Sending update_predecessor request: {update_predecessor_request}")

                update_response = self.send_request(self.successor["ip"], self.successor["port"], update_predecessor_request)
                print(f"[NODE {self.node_id}] Update predecessor response: {update_response}")

            else:
                print(f"[ERROR] Could not find successor: {successor_response['message']}")

        except Exception as e:
            print(f"[ERROR] Failed to join network: {e}")



    def find_successor(self, node_id):
        """Finds the correct successor for a joining node."""
        print(f"[DEBUG] find_successor() called for node_id: {node_id}")

        # If the current node is its own successor, return itself (Bootstrap case)
        if self.successor["node_id"] == self.node_id:
            print(f"[DEBUG] Returning bootstrap node as successor: {self.successor}")
            return {"status": "success", "successor": self.successor}

        # If this node is the correct successor
        if self.node_id < node_id <= self.successor["node_id"]:
            print(f"[DEBUG] Returning successor: {self.successor}")
            return {"status": "success", "successor": self.successor}

        # If this node is not the correct successor, forward the request
        print(f"[DEBUG] Forwarding find_successor request to {self.successor}")
        forward_request = {"command": "find_successor", "node_id": node_id}
        return self.send_request(self.successor["ip"], self.successor["port"], forward_request)





    def update_predecessor(self, node_id, ip, port):
        """ Ορίζει τον νέο predecessor """
        self.predecessor = {"node_id": node_id, "ip": ip, "port": port}
        print(f"[NODE {self.node_id}] Predecessor updated: {self.predecessor}")
        return {"status": "success", "message": "Predecessor updated"}


    def send_request(self, ip, port, request):
        """ Στέλνει request σε άλλον κόμβο """
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((ip, port))
            client.send(json.dumps(request).encode())
            response = client.recv(1024).decode()
            client.close()
            return json.loads(response)
        except Exception as e:
            return {"status": "error", "message": str(e)}




    def handle_request(self, conn):
        """ Διαχειρίζεται εισερχόμενα αιτήματα από άλλους κόμβους """
        try:
            data = conn.recv(1024).decode()
            if data:
                request = json.loads(data)
                print(f"[DEBUG] Received request: {request}")  # Προσθέτουμε debugging
                response = self.process_request(request)
                conn.send(json.dumps(response).encode())
        except Exception as e:
            print(f"[ERROR] Request handling failed: {e}")
        finally:
            conn.close()


    def process_request(self, request):
        """ Διαχειρίζεται τα αιτήματα insert, query, delete, shutdown """
        command = request.get("command")
        key = request.get("key")
        value = request.get("value")
        node_id = request.get("node_id")

        if command == "insert":
            return self.insert(key, value)
        elif command == "query":
            return self.query(key)
        elif command == "delete":
            return self.delete(key)
        elif command == "find_successor":
            return self.find_successor(node_id)  # Call find_successor with node_id
        elif command == "update_predecessor":
            return self.update_predecessor(node_id, request["ip"], request["port"])
        #elif command == "shutdown":
        #    return self.shutdown(conn)  # Περνάμε τη σύνδεση
        return {"status": "error", "message": f"Invalid command received: {command}"}

    def insert(self, key, value):
        """ Αποθηκεύει ένα τραγούδι στο DHT """
        hashed_key = int(hashlib.sha1(key.encode()).hexdigest(), 16) % (2**160)
        self.data_store[hashed_key] = value
        return {"status": "success", "message": f"Inserted {key} -> {value}"}

    def query(self, key):
        """ Αναζητά ένα τραγούδι στο DHT """
        hashed_key = int(hashlib.sha1(key.encode()).hexdigest(), 16) % (2**160)
        if hashed_key in self.data_store:
            return {"status": "success", "value": self.data_store[hashed_key]}
        return {"status": "error", "message": "Key not found"}

    def delete(self, key):
        """ Διαγράφει ένα τραγούδι από το DHT """
        hashed_key = int(hashlib.sha1(key.encode()).hexdigest(), 16) % (2**160)
        if hashed_key in self.data_store:
            del self.data_store[hashed_key]
            return {"status": "success", "message": f"Deleted {key}"}
        return {"status": "error", "message": "Key not found"}

    #def shutdown(self, conn):
        """Τερματίζει τον server σωστά χωρίς να κλείνει απότομα τις συνδέσεις"""
        print("[NODE] Shutting down...")

        response = {"status": "success", "message": "Server shutting down"}
        
        try:
            conn.send(json.dumps(response).encode())  # Στέλνει απάντηση πριν το exit
            time.sleep(1)  # Δίνει χρόνο στον client να λάβει την απάντηση
        except Exception as e:
            print(f"[ERROR] Could not send shutdown response: {e}")

        os._exit(0)  # Τερματίζει το πρόγραμμα

    def join_network(self, bootstrap_ip, bootstrap_port):
        """ Ενώνει τον κόμβο στο Chord δίκτυο """
        print(f"[NODE {self.node_id}] Joining network via {bootstrap_ip}:{bootstrap_port}")
        self.successor = (bootstrap_ip, bootstrap_port)  # Προσωρινά ορίζουμε ως successor τον bootstrap

# Εκκίνηση κόμβου
# Node startup logic
if __name__ == "__main__":
    if len(sys.argv) == 3:
        # This is the bootstrap node
        ip = sys.argv[1]
        port = int(sys.argv[2])
        node = ChordNode(ip, port)
    
    elif len(sys.argv) == 5:
        # This is a new node joining an existing network
        ip = sys.argv[1]
        port = int(sys.argv[2])
        bootstrap_ip = sys.argv[3]
        bootstrap_port = int(sys.argv[4])
        node = ChordNode(ip, port, bootstrap_ip, bootstrap_port)

    else:
        print("Usage:")
        print("  Bootstrap node: python node.py <ip> <port>")
        print("  Joining node:  python node.py <ip> <port> <bootstrap_ip> <bootstrap_port>")
        sys.exit(1)

