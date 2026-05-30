import httpx
import asyncio
import json
import os
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from tuiComponents.messages import DebugMsg, EventMsg


class TokenExpiredError(Exception):
    pass


class ChallengeCategories:
  """Class to manage challenge categories."""

  def __init__(self) -> None:
    self.id_to_name = {}
    self.name_to_id = {}

  async def load(self, api_session):
    categories = (await api_session.async_get("/api/v4/challenge/categories/list")).get("info", [])
    for cat in categories:
      cat_id = cat.get("id")
      cat_name = cat.get("name")
      self.id_to_name[cat_id] = cat_name
      self.name_to_id[cat_name] = cat_id

  def __repr__(self):
    return f"ChallengeCategories({list(self.name_to_id.keys())})"
     
# for debugging via burp — set env USE_BURP=1 to enable
burp_proxy = httpx.Proxy("http://127.0.0.1:8080") if os.environ.get("USE_BURP") else None

class HTBApiSession:
  APITOKEN : str = ""
  base_url = "https://labs.hackthebox.com"
  headers = {
          "Accept": "application/json, text/plain, */*",
          "User-Agent": "HTBClient/1.0.0"
  }
  CRRENT_USER : dict 
  CHALLENGE_CATEGORIES : dict 
  CACHE = None
  
  
  def __init__(self, token: str, app=None) -> None:
    self.APITOKEN = token
    self.app = app
    self.headers = dict(self.headers)
    self.headers["Authorization"] = f"Bearer {self.APITOKEN}"

    self.CRRENT_USER = {}
    self.CHALLENGE_CATEGORIES = None

    self.CACHE = {}
    self.USE_CACHE = 0
    workdir = getattr(app, 'WORKDIR', '.') if app else '.'
    self._CACHE_FILE = os.path.join(workdir, "req_cache.json")
    os.makedirs(workdir, exist_ok=True)
    try:
      self.CACHE = json.load(open(self._CACHE_FILE))
    except Exception:
      pass
    self._initialized = False
    self._init_lock = asyncio.Lock()
    self._client = None
    self._token_dead = False

  def _build_client_kw(self):
    kw = {"verify": False}
    if burp_proxy:
      kw["proxy"] = burp_proxy
    return kw

  async def _get_client(self):
    if self._client is None or self._client.is_closed:
      self._client = httpx.AsyncClient(**self._build_client_kw())
    return self._client

  async def close(self):
    if self._client and not self._client.is_closed:
      await self._client.aclose()
      self._client = None

  async def ensure_init(self):
    async with self._init_lock:
      if self._initialized:
        return
      self.app.post_message(EventMsg("API::Initialized"))
      await self._async_load_current_user()
      await self._async_load_categories()
      self._initialized = True

  async def _async_load_current_user(self):
    self.CRRENT_USER = await self.async_get("/api/v4/user/info")
    self.app.post_message(DebugMsg("API::current user", self.CRRENT_USER))

  async def _async_load_categories(self):
    self.CHALLENGE_CATEGORIES = ChallengeCategories()
    await self.CHALLENGE_CATEGORIES.load(self)
    self.app.post_message(DebugMsg("API::loaded categories ", self.CHALLENGE_CATEGORIES))
  
  def load_current_user(self):
    self.CRRENT_USER = self.do_get("/api/v4/user/info")

  def load_categories(self):
    self.CHALLENGE_CATEGORIES = ChallengeCategories()
    categories = self.do_get("/api/v4/challenge/categories/list").get("info", [])
    for cat in categories:
      self.CHALLENGE_CATEGORIES.id_to_name[cat["id"]] = cat["name"]
      self.CHALLENGE_CATEGORIES.name_to_id[cat["name"]] = cat["id"]
  
  def _make_url(self, endpoint):
    return f"{self.base_url}{endpoint}"
    
  async def async_get(self, endpoint:str, **kw):
    return await self.make_async_request(
      method = "GET",
      endpoint = endpoint,
      **kw
    )
  
  async def async_post(self, endpoint:str, data:dict, **kw):
    return await self.make_async_request(
      method = "POST",
      endpoint = endpoint,
      json = data,
      cache_this = 0,
      **kw
    )

  def do_get(self, endpoint:str,**kw):
    return self.make_sync_request(
      method = "GET",
      endpoint = endpoint,
      **kw
    )

  def do_post(self, endpoint:str, data:dict, **kw):
    return self.make_sync_request(
      method = "POST",
      endpoint = endpoint,
      json = data,
      cache_this=0,
      **kw
    )

  def make_sync_request(self, method, endpoint, **kw):
    try:
      loop = asyncio.get_running_loop()
    except RuntimeError:
      loop = None
    if loop and loop.is_running():
      import concurrent.futures
      with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, self.make_async_request(method, endpoint, **kw)).result()
    return asyncio.run(
      self.make_async_request(
        method,
        endpoint,
        **kw
      )
    )
  
  async def make_async_request(self, method="GET", endpoint="/",  cache_this=1, **kw):
    if self._token_dead:
      raise TokenExpiredError("HTB API token is expired or invalid")
    URL = self._make_url(endpoint)
    req_id = f"{method}_{endpoint}_{str(kw)}"
    self.app.post_message(DebugMsg(
      f"API::REQUEST {method}", url=URL, **kw
    ))
    if self.USE_CACHE and cache_this and self.is_in_cache(req_id):
      data = self.get_from_cache(req_id)
      self.app.post_message(DebugMsg(
        f"API::CACHED {method}", str(data)[:20]+ "... ... "
      ))
      return data
    
    client = await self._get_client()
    response = await client.request(
      method = method,
      url= URL,
      headers=self.headers,
      **kw
    )
    if response.status_code == 401:
      self._token_dead = True
      self.app.post_message(EventMsg("API::TOKEN EXPIRED or INVALID — update HTB_TOKEN and restart"))
      self.app.notify("Token expired or invalid. Update HTB_TOKEN and restart.", severity="error", timeout=10)
      raise TokenExpiredError("HTB API token is expired or invalid")
    if response.status_code not in (200, 201):
      body = ""
      try:
        body = response.json().get("message", response.text[:200])
      except Exception:
        body = response.text[:200]
      raise Exception(f"Request {method} to {URL} fail with {response.status_code}: {body}")
    data = response.json()
    self.app.post_message(DebugMsg(
      f"API::RESULT {method}", response, str(data)[:20]+ "... ... "
    ))
    if self.USE_CACHE and cache_this:
      self.save_to_cache(req_id, data)
    return data
    
    

  def is_in_cache(self, req_id):
    return req_id in self.CACHE
  
  def get_from_cache(self, req_id):
    return self.CACHE.get(req_id, {})

  def save_to_cache(self, req_id, data):
    self.CACHE[req_id] = data
    json.dump(self.CACHE, open(self._CACHE_FILE, "w"))
    self.app.post_message(DebugMsg(f"API::CACHE SAVED",req_id))


class HTBCTFSession:

    base_url = "https://ctf.hackthebox.com"

    def __init__(self, token, app=None):
        self.token = token
        self.app = app
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        self._client = None

    def _build_client_kw(self):
        kw = {"verify": False}
        if burp_proxy:
            kw["proxy"] = burp_proxy
        return kw

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(**self._build_client_kw())
        return self._client

    async def get(self, endpoint, **kw):
        client = await self._get_client()
        url = f"{self.base_url}{endpoint}"
        r = await client.get(url, headers=self.headers, timeout=15, **kw)
        if r.status_code == 401:
            if self.app:
                self.app.notify("CTF Token expired or invalid", severity="error", timeout=10)
            raise Exception("CTF API: token expired")
        if r.status_code != 200:
            raise Exception(f"CTF API {r.status_code}: {endpoint}")
        return r.json()

    async def download_bytes(self, endpoint):
        client = await self._get_client()
        url = f"{self.base_url}{endpoint}"
        r = await client.get(url, headers=self.headers, timeout=60, follow_redirects=True)
        if r.status_code == 401:
            raise Exception("CTF API: token expired")
        if r.status_code != 200:
            raise Exception(f"CTF download {r.status_code}: {endpoint}")
        return r.content

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None