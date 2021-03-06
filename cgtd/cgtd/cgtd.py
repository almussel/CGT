#!/usr/bin/python
import logging
import json
import cStringIO
import ipfsApi
from ethjsonrpc import EthJsonRpc
from flask import Flask, request, jsonify, g
from flask_restplus import Api, Resource

app = Flask(__name__, static_url_path="")
logging.basicConfig(level=logging.DEBUG)

with open("VarStore.json", "r") as f:
    eth = EthJsonRpc("ethereum", 8545)
    contract = json.loads(f.read())
    # REMIND: Move this into the compile step external to the server
    contract["address"] = eth.get_contract_address(contract["transaction"])
    logging.debug("Contract at {}".format(contract["address"]))
    eth_filter = eth.eth_newFilter(from_block=0, address=contract["address"])


@app.before_request
def connect_to_ipfs():
    g.ipfs = ipfsApi.Client("ipfs", 5001)
    g.eth = EthJsonRpc("ethereum", 8545)


@app.route("/")
def index():
    return app.send_static_file("index.html")


"""
RESTful API
"""
api = Api(app, version="v0", title="Cancer Gene Trust API", doc="/api",
          description="""
RESTful API for the Cancer Gene Trust Daemon (cgtd)
""")


@api.route("/v0/ipfs")
class IPFSAPI(Resource):
    def get(self):
        """ Return ipfs id. """
        return jsonify(g.ipfs.id())


@api.route("/v0/ethereum")
class EthereumAPI(Resource):
    def get(self):
        """ Return ethereum account. """
        return jsonify(accounts=g.eth.eth_accounts(),
                       coinbase=g.eth.eth_coinbase())


@api.route("/v0/submissions")
class SubmissionListAPI(Resource):

    def get(self):
        """
        Get a list of all submissions by account

        Returns a dict of path lists by steward account:
            {account: [ipfs path, ipfs path], account...}

        Note: This uses an Ethereum filter and therefore recent
        submissions may not show up until sufficient mining has
        occurred.

        REMIND: Should lazily update the ipns list for the steward
        so that apps don't have to mine the Ethereum block chain
        to get a full list but rather do a simple $.getJSON()
        """
        # Older ipns storage for full list of submissions
        # steward = json.loads(g.ipfs.cat(g.ipfs.name_resolve()["Path"]))
        # return jsonify(submissions=steward["submissions"])

        # Update steward submissions list and publish to ipns
        # steward = json.loads(g.ipfs.cat(g.ipfs.name_resolve()["Path"]))
        # if path not in steward["submissions"]:
        #     steward["submissions"].append(path)
        #     steward_path = g.ipfs.add(
        #         cStringIO.StringIO(json.dumps(steward)))[1]["Hash"]
        #     g.ipfs.name_publish(steward_path)
        #     logging.debug("{} added to submissions list".format(path))
        # else:
        #     logging.debug("{} already in submissions list".format(path))

        # Get a list of all transactions and de-dupe via set()
        transactions = set((t['data'][26:66], t['data'][194:-24].decode("hex"))
                           for t in g.eth.eth_getFilterLogs(eth_filter))

        # Create a dict of account: [list of pathes to submissions]
        submissions = {}
        for account, path in transactions:
            submissions.setdefault(account, []).append(path)
        return jsonify(submissions=submissions)

    def post(self):
        """
        Add posted files and json manifest to ipfs.

        Add all posted files to ipfs along with a json manifest file which
        includes the ipfs path for each file as well as any form fields.

        Returns the submission manifest and its path in ipfs.
        """
        manifest = {"fields": {key: value for key, value in
                               request.form.items()}}
        manifest["files"] = [{"name": f.filename, "path":
                              "/ipfs/{}".format(g.ipfs.add(f)[1]["Hash"])}
                             for f in request.files.getlist("file")]
        logging.debug("Manifest:".format(manifest))
        path = "/ipfs/{}".format(
            g.ipfs.add(cStringIO.StringIO(json.dumps(manifest)))[1]["Hash"])
        logging.info("Path: {}".format(path))

        logging.debug("Adding to Ethereum block chain")
        transaction = g.eth.call_with_transaction(g.eth.eth_coinbase(),
                                                  contract["address"],
                                                  'saveVar(bytes)', [path])
        logging.debug("Transaction: {}".format(transaction))
        logging.debug("Transaction on blockchain: {}".format(g.eth.eth_getTransactionByHash(transaction)))

        return jsonify(path=path, manifest=manifest)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
