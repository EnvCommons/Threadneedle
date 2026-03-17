from openreward.environments import Server

from threadneedle import Threadneedle

if __name__ == "__main__":
    server = Server([Threadneedle])
    server.run()
