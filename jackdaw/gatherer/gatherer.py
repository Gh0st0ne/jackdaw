
import pathlib
import asyncio

from jackdaw import logger
from jackdaw.gatherer.smb.smb import SMBGatherer
from jackdaw.gatherer.smb.smb_file import SMBShareGathererSettings, ShareGathererManager
from jackdaw.gatherer.ldap.aioldap import LDAPGatherer

from aiosmb.commons.connection.url import SMBConnectionURL
from msldap.commons.url import MSLDAPURLDecoder
from jackdaw.gatherer.edgecalc import EdgeCalc
from jackdaw.gatherer.rdns.rdns import RDNS
from tqdm import tqdm
from jackdaw.gatherer.progress import *

class Gatherer:
	def __init__(self, db_url, work_dir, ldap_url, smb_url, ad_id = None, calc_edges = True, ldap_worker_cnt = 4, smb_worker_cnt = 100, mp_pool = None, smb_enum_shares = False, smb_gather_types = ['all'], progress_queue = None, show_progress = True, dns = None):
		self.db_url = db_url
		self.work_dir = work_dir
		self.mp_pool = mp_pool
		self.ldap_worker_cnt = ldap_worker_cnt
		self.smb_worker_cnt = smb_worker_cnt
		self.smb_enum_shares = smb_enum_shares
		self.smb_gather_types = smb_gather_types
		self.ad_id = ad_id
		self.calculate_edges = calc_edges
		self.dns_server = dns
		self.resumption = False
		if ad_id is not None:
			self.resumption = True

		self.smb_url = smb_url
		self.ldap_url = ldap_url
		self.progress_queue = progress_queue
		self.show_progress = show_progress
		self.smb_folder_depth = 1

		self.graph_id = None
		self.ldap_task = None
		self.ldap_mgr = None
		self.ldap_work_dir = None
		self.smb_task = None
		self.smb_mgr = None
		self.smb_work_dir = None
		self.rdns_resolver = None
		self.progress_task = None
	
	async def print_progress(self):
		logger.debug('Setting up progress bars')
		pos = 0
		if self.ldap_url is not None:
			ldap_basic_pbar        = tqdm(desc = 'LDAP basic enum       ', ascii=True, position=pos)
			pos += 1
			ldap_sd_pbar           = tqdm(desc = 'LDAP SD enum          ', ascii=True, position=pos)
			pos += 1
			ldap_sdupload_pbar     = tqdm(desc = 'LDAP SD upload        ', ascii=True, position=pos)
			pos += 1
			ldap_member_pbar       = tqdm(desc = 'LDAP membership enum  ', ascii=True, position=pos)
			pos += 1
			ldap_memberupload_pbar = tqdm(desc = 'LDAP membership upload', ascii=True, position=pos)
			pos += 1
		if self.smb_url is not None:
			smb_pbar               = tqdm(desc = 'SMB enum              ', ascii=True, position=pos)
			pos += 1
		if self.calculate_edges is True:
			sdcalc_pbar            = tqdm(desc = 'SD edges calc         ', ascii=True, position=pos)
			pos += 1
			sdcalcupload_pbar      = tqdm(desc = 'SD edges upload       ', ascii=True, position=pos)
			pos += 1

		logger.debug('waiting for progress messages')
		while True:
			msg = await self.progress_queue.get()
			try:
				if msg.type == GathererProgressType.BASIC:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if ldap_basic_pbar.total is None:
							ldap_basic_pbar.total = msg.total
						
						ldap_basic_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						ldap_basic_pbar.refresh()

				elif msg.type == GathererProgressType.SD:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if ldap_sd_pbar.total is None:
							ldap_sd_pbar.total = msg.total
						
						ldap_sd_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						ldap_sd_pbar.refresh()

				elif msg.type == GathererProgressType.SDUPLOAD:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if ldap_sdupload_pbar.total is None:
							ldap_sdupload_pbar.total = msg.total
						
						ldap_sdupload_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						ldap_sdupload_pbar.refresh()

				elif msg.type == GathererProgressType.MEMBERS:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if ldap_member_pbar.total is None:
							ldap_member_pbar.total = msg.total
						
						ldap_member_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						ldap_member_pbar.refresh()
				
				elif msg.type == GathererProgressType.MEMBERSUPLOAD:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if ldap_memberupload_pbar.total is None:
							ldap_memberupload_pbar.total = msg.total
						
						ldap_memberupload_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						ldap_memberupload_pbar.refresh()

				elif msg.type == GathererProgressType.SMB:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if smb_pbar.total is None:
							smb_pbar.total = msg.total
						
						smb_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						smb_pbar.refresh()

				elif msg.type == GathererProgressType.SDCALC:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if sdcalc_pbar.total is None:
							sdcalc_pbar.total = msg.total
						
						sdcalc_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						sdcalc_pbar.refresh()

				elif msg.type == GathererProgressType.SDCALCUPLOAD:
					if msg.msg_type == MSGTYPE.PROGRESS:
						if sdcalcupload_pbar.total is None:
							sdcalcupload_pbar.total = msg.total
						
						sdcalcupload_pbar.update(msg.step_size)

					if msg.msg_type == MSGTYPE.FINISHED:
						sdcalcupload_pbar.refresh()

			except Exception as e:
				print(e)

	async def gather_ldap(self):
		try:
			gatherer = LDAPGatherer(
				self.db_url,
				self.ldap_mgr,
				agent_cnt=self.ldap_worker_cnt, 
				work_dir = self.ldap_work_dir,
				progress_queue = self.progress_queue,
				show_progress = False,
				ad_id = self.ad_id #this should be none, or resumption is indicated!
			)
			ad_id, graph_id, err = await gatherer.run()
			if err is not None:
				return None, None, err
			logger.debug('ADInfo entry successfully created with ID %s' % ad_id)
			return ad_id, graph_id, None
		except Exception as e:
			return None, None, e

	async def gather_smb(self):
		try:
			mgr = SMBGatherer(
				self.db_url,
				self.ad_id,
				self.smb_mgr, 
				worker_cnt=self.smb_worker_cnt,
				rdns_resolver = self.rdns_resolver,
				progress_queue = self.progress_queue,
				show_progress = False
			)
			mgr.gathering_type = self.smb_gather_types
			mgr.target_ad = self.ad_id
			await mgr.run()
			return True, None
		except Exception as e:
			return None, e

	async def share_enum(self):
		settings_base = SMBShareGathererSettings(self.ad_id, self.smb_mgr, None, None, None)
		settings_base.dir_depth = self.smb_folder_depth
		mgr = ShareGathererManager(settings_base, db_conn = self.db_conn, worker_cnt = args.smb_workers)
		mgr.run()

	async def calc_edges(self):
		try:
			ec = EdgeCalc(
				self.db_url, 
				self.ad_id, 
				self.graph_id, 
				buffer_size = 100, 
				show_progress = False, 
				progress_queue = self.progress_queue, 
				worker_count = None, 
				mp_pool = self.mp_pool
			)
			res, err = await ec.run()
			return res, err
		except Exception as e:
			return False, e

	async def setup(self):
		try:
			logger.debug('Setting up working directory')
			if self.work_dir is not None:
				if isinstance(self.work_dir, str):
					self.work_dir = pathlib.Path(self.work_dir)
			else:
				self.work_dir = pathlib.Path()

			self.work_dir.mkdir(parents=True, exist_ok=True)
			self.ldap_work_dir = self.work_dir.joinpath('ldap')
			self.ldap_work_dir.mkdir(parents=True, exist_ok=True)
			self.smb_work_dir = self.work_dir.joinpath('smb')
			self.smb_work_dir.mkdir(parents=True, exist_ok=True)


			logger.debug('Setting up connection objects')
			if self.dns_server is not None:
				self.rdns_resolver = RDNS(server = self.dns_server, protocol = 'TCP', cache = True)

			if self.ldap_url is not None:
				self.ldap_mgr = MSLDAPURLDecoder(self.ldap_url)
				if self.rdns_resolver is None:
					self.rdns_resolver = RDNS(server = self.ldap_mgr.ldap_host, protocol = 'TCP', cache = True)

			if self.smb_url is not None:
				self.smb_mgr = SMBConnectionURL(self.smb_url)
				if self.rdns_resolver is None:
					self.rdns_resolver = RDNS(server = self.smb_mgr.ip, protocol = 'TCP', cache = True)
			

			logger.debug('Setting up database connection')

			
			
			if self.show_progress is True and self.progress_queue is None:
				self.progress_queue = asyncio.Queue()
				self.progress_task = asyncio.create_task(self.print_progress())
			
			return True, None
		except Exception as e:
			return False, e


	async def run(self):
		try:
			_, err = await self.setup()
			if err is not None:
				raise err

			if self.ldap_mgr is not None:
				self.ad_id, self.graph_id, err = await self.gather_ldap()
				if err is not None:
					raise err

			if self.smb_url is not None:
				_, err = await self.gather_smb()
				if err is not None:
					raise err
			
			if self.smb_enum_shares is True and self.smb_url is not None:
				_, err = await self.share_enum()
				if err is not None:
					raise err
			
			if self.calculate_edges is True:
				_, err = await self.calc_edges()
				if err is not None:
					raise err
			return True, None
		except Exception as e:
			print(e)
			return False, e



		