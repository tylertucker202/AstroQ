from os.path import isfile
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import subprocess
import yaml
from urllib.parse import quote_plus

class db_conn_mongo(object):

    def __init__(self, configFile, collection = None):

        self.error = None
        self.readonly = False

        #parse config file
        if not isfile(configFile):
            self.error = "DATABASE_CONFIG_ERROR"
            return None
        with open(configFile) as f: self.config = yaml.safe_load(f)
        if 'kpf_cc' not in self.config:
            self.error = "DATABASE_CONFIG_ERROR"
            return None
        self.config = self.config['database']

        self.client     = None
        collection = collection if collection else self.config["collection"]
        self.connect('kpf_cc', collection)


    def connect(self, database, collection):
        """
        Connect to the specified database.  If primary server is down and backup
        is specified, then connect to it.  This also set the readOnly flag to 1.
        """

        #get db connect data
        server         = self.config["server"]
        readonlyserver = self.config.get("readonlyserver", server)
        cmd = ["timeout", "0.5", "ping", "-c", "1", server]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            p.wait()
            output = p.stdout.readlines()
            if len(output) == 0:
                server = readonlyserver
                self.readonly = True
        except:
            server = readonlyserver
            self.readonly = True
        finally:
            p.stdout.close()

        user           = self.config["user"]
        pwd            = self.config["pwd"]
        try:
            server = f"{user}:{quote_plus(pwd)}@{quote_plus(server)}"
            auth = ""
            if self.config.get("auth"):
                auth = f'?authSource={self.config["auth"]}'
            # Primary connection
            url = f"mongodb://{server}/{database}{auth}"
            self.client = MongoClient(url)
        except ConnectionFailure:
            self.error = "PYMONGO_CONNECTION_ERROR"
            self.client = None

        self.collection = self.client[database][collection]


    def close(self):
        """
        Closes the current database connection
        """

        if self.client:
            self.client.close()


    def query(self, qtype, parameters):

        if qtype == "find":
            #find by query
            qresults = collection.find(query)

        #put in list
        configs = []
        for item in qresults:
            item["_id"] = str(item["_id"])
            configs.append(item)

        return configs

