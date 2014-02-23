import TS3
from TS3.utils import *

import threading
import time
import sqlite3
import os

class Database:
	def __init__(self):
		# Path to the database
		self.path = os.path.join(os.path.dirname(__file__), "database.sqlite")
		# Open a connection
		self.conn = sqlite3.connect(self.path)

	def get_channel_name(self, user_id):
		cur = self.conn.execute("SELECT * FROM channels WHERE user = ?", (user_id,))
		result = cur.fetchone()
		if result == None:
			return result
		return result[1]

	def set_channel_name(self, user_id, channel, description = ""):
		cur = self.conn.execute("INSERT OR REPLACE INTO channels (user, name, description) VALUES (?, ?, ?)", (user_id, channel, description))
		self.conn.commit()

database = Database()

# database.set_channel_name("TestUser", "My Channel Name")
# print database.get_channel_name("Nobody here")
# print database.get_channel_name("TestUser")

class DatabaseIDManager:

	def __init__(self, conn):
		self.conn = conn
		self.ids = {}
		self.callbacks = {}

		for client in Client.get_all_clients(conn):
			client.request_dbid()

	def update(self, uid, dbid):
		self.ids[uid] = dbid
		try:
			self.callbacks[uid](dbid)
			del self.callbacks[uid]
		except:
			pass

	def get_dbid(self, user, callback = None):
		uid = user.get_unique_identifier()
		if uid in self.ids:
			if callback != None:
				callback(self.ids[uid])
			return self.ids[uid]
		elif callback != None:
			self.callbacks[uid] = callback
			user.request_dbid()
		else:
			return None

class ChannelOwner:

	def __init__(self):
		self.owner = {}

	def get(self, channel_id):
		try:
			return self.owner[channel_id]
		except:
			return None

	def set(self, channel_id, client):
		self.owner[channel_id] = client


PARENT_CHANNEL_NAME = "Personal Channels"
CHANNEL_FACTORY_NAME = "Channel Factory"
DEFAULT_CHANNEL_NAME = "New Channel"
CHANNEL_ADMIN_GROUP = 5

class ServerState(TS3.ClientEventHandler):
	dbid_manager = None

	def __init__(self):
		self.connection = TS3.Connection()
		self.parent_channel = None
		handles = self.connection.getServerConnectionHandlerList()
		if len(handles) > 0:
			self.connect(handles[0])

	def find_parent_channel(self):
		channels = Channel.get_all_channels(self.connection)
		for channel in channels:
			if channel.get_name() == PARENT_CHANNEL_NAME:
				self.parent_channel = channel
				return True
		return False

	def connect(self, serverConnectionID):
		print "Setting up server state"
		self.connection = TS3.Connection(serverConnectionID)
		if not self.find_parent_channel():
			print "Failed to find parent channel"
			return
		if not self.channel_factory_exists():
			self.create_channel_factory()
		self.dbid_manager = DatabaseIDManager(self.connection)
		self.owner_db = ChannelOwner()

	def channel_factory_exists(self):
		channels = Channel.get_all_channels(self.connection)
		for channel in channels:
			if channel.get_name() == CHANNEL_FACTORY_NAME:
				return True
		return False

	def is_channel_factory(self, channel_id):
		channel = Channel(self.connection, channel_id)
		if channel.get_parent() == self.parent_channel:
			if channel.get_name() == CHANNEL_FACTORY_NAME:
				return True

		return False

	def create_channel_factory(self):
		Channel.create_channel(self.connection, CHANNEL_FACTORY_NAME, self.parent_channel)

	def channel_exists(self, name):
		for channel in Channel.get_all_channels(self.connection):
			if channel.get_name() == name:
				return True
		return False

	def ensure_channel_name(self, name):
		name = name.rsplit("#", 1)[0]
		if not self.channel_exists(name):
			return name
		for i in range(1, 50):
			new_name = "%s#%s" % (name, i)
			if not self.channel_exists(new_name):
				return new_name

	def delete_empty_channels(self):
		for channel in self.parent_channel.get_children():
			if self.is_channel_factory(channel.channel_id):
				return False
			if len(channel.get_clients()) == 0:
				channel.delete()

	def ensure_channel_factory(self):
		if not self.channel_factory_exists():
			self.create_channel_factory()

	def store_channel_name(self, channel_id):
		owner = self.owner_db.get(channel_id)
		if not owner:
			print "Failed to find owner of channel %s" % channel_id
			return
		channel = Channel(self.connection, channel_id)
		name = channel.get_name()
		database.set_channel_name(owner.get_unique_identifier(), name)


	def create_channel_for_user(self, client_id, channel_id):
		client = Client(self.connection, client_id)
		uid = client.get_unique_identifier()
		channel_name = database.get_channel_name(uid)
		if not channel_name:
			channel_name = DEFAULT_CHANNEL_NAME
		channel_name = self.ensure_channel_name(channel_name)
		channel = Channel(self.connection, channel_id)
		channel.set_name(channel_name)
		channel.flush_updates()
		self.create_channel_factory()
		self.dbid_manager.get_dbid(client, lambda dbid: channel.set_client_channel_group(CHANNEL_ADMIN_GROUP, dbid))
		self.owner_db.set(channel_id, client)

	# Begin event handling
	def onConnectStatusChangeEvent(self, connection, newStatus, errorNumber, **kwargs):
		if newStatus == TS3.ConnectStatus.STATUS_CONNECTION_ESTABLISHED:
			print "New Connection established"
			self.connect(connection.get_server_connection_id())

	def onNewChannelCreatedEvent(self, connection, **kwargs):
		self.ensure_channel_factory()

	def onClientMoveEvent(self,
		connection,
		clientID,
		oldChannelID,
		newChannelID,
		**kwargs):
		self.delete_empty_channels()
		if self.is_channel_factory(newChannelID):
			self.create_channel_for_user(clientID, newChannelID)

	def onClientMoveMovedEvent(self, connection, clientID, newChannelID, **kwargs):
		self.delete_empty_channels()
		if self.is_channel_factory(newChannelID):
			self.create_channel_for_user(clientID, newChannelID)

	def onTextMessageEvent(self, connection, targetMode, toID, fromID, fromName, fromUniqueIdentifier, message, ffIgnored, **kwargs):
		if message == "!test":
			print TS3.ConnectStatus.STATUS_CONNECTION_ESTABLISHED

	def onClientDBIDfromUIDEvent(self, connection, uniqueClientIdentifier, clientDatabaseID, **kwargs):
		self.dbid_manager.update(uniqueClientIdentifier, clientDatabaseID)

	def onUpdateChannelEditedEvent(self, connection, channelID, **kwargs):
		self.store_channel_name(channelID)

TS3.register_callback_handler(ServerState())