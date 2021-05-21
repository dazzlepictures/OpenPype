# -*- coding: utf-8 -*-
"""Create ``Render`` instance in Maya."""
import os
import json
import appdirs
import requests

import six

from maya import cmds
import maya.app.renderSetup.model.renderSetup as renderSetup

from pype.hosts.maya import (
    lib,
    plugin
)


class CreateRender(plugin.Creator):
    """Create *render* instance.

    Render instances are not actually published, they hold options for
    collecting of render data. It render instance is present, it will trigger
    collection of render layers, AOVs, cameras for either direct submission
    to render farm or export as various standalone formats (like V-Rays
    ``vrscenes`` or Arnolds ``ass`` files) and then submitting them to render
    farm.

    Instance has following attributes::

        primaryPool (list of str): Primary list of slave machine pool to use.
        secondaryPool (list of str): Optional secondary list of slave pools.
        suspendPublishJob (bool): Suspend the job after it is submitted.
        extendFrames (bool): Use already existing frames from previous version
            to extend current render.
        overrideExistingFrame (bool): Overwrite already existing frames.
        priority (int): Submitted job priority
        framesPerTask (int): How many frames per task to render. This is
            basically job division on render farm.
        whitelist (list of str): White list of slave machines
        machineList (list of str): Specific list of slave machines to use
        useMayaBatch (bool): Use Maya batch mode to render as opposite to
            Maya interactive mode. This consumes different licenses.
        vrscene (bool): Submit as ``vrscene`` file for standalone V-Ray
            renderer.
        ass (bool): Submit as ``ass`` file for standalone Arnold renderer.
        tileRendering (bool): Instance is set to tile rendering mode. We
            won't submit actuall render, but we'll make publish job to wait
            for Tile Assemly job done and then publish.

    See Also:
        https://pype.club/docs/artist_hosts_maya#creating-basic-render-setup

    """

    label = "Render"
    family = "rendering"
    icon = "eye"
    defaults = ["Main"]

    _token = None
    _user = None
    _password = None

    # renderSetup instance
    _rs = None

    _image_prefix_nodes = {
        'mentalray': 'defaultRenderGlobals.imageFilePrefix',
        'vray': 'vraySettings.fileNamePrefix',
        'arnold': 'defaultRenderGlobals.imageFilePrefix',
        'renderman': 'defaultRenderGlobals.imageFilePrefix',
        'redshift': 'defaultRenderGlobals.imageFilePrefix',
        'mayahardware2': 'defaultRenderGlobals.imageFilePrefix'
    }

    _image_prefixes = {
        'mentalray': 'maya/<Scene>/<RenderLayer>/<RenderLayer>_<RenderPass>',
        'vray': 'maya/<scene>/<Layer>/<Layer>',
        'arnold': 'maya/<Scene>/<RenderLayer>/<RenderLayer>_<RenderPass>',
        'renderman': 'maya/<Scene>/<layer>/<layer>_<aov>',
        'redshift': 'maya/<Scene>/<RenderLayer>/<RenderLayer>_<RenderPass>',
        'mayahardware2': 'maya/<Scene>/<RenderLayer>/<RenderLayer>'
    }

    deadline_servers = {}

    def __init__(self, *args, **kwargs):
        """Constructor."""
        super(CreateRender, self).__init__(*args, **kwargs)

    def process(self):
        """Entry point."""
        exists = cmds.ls(self.name)
        if exists:
            cmds.warning("%s already exists." % exists[0])
            return

        use_selection = self.options.get("useSelection")
        with lib.undo_chunk():
            self._create_render_settings()
            self.instance = super(CreateRender, self).process()
            # create namespace with instance
            index = 1
            namespace_name = "_{}".format(str(self.instance))
            try:
                cmds.namespace(rm=namespace_name)
            except RuntimeError:
                # namespace is not empty, so we leave it untouched
                pass

            while(cmds.namespace(exists=namespace_name)):
                namespace_name = "_{}{}".format(str(self.instance), index)
                index += 1

            namespace = cmds.namespace(add=namespace_name)

            # add Deadline server selection list
            cmds.scriptJob(
                attributeChange=[
                    "{}.deadlineServers".format(self.instance),
                    self._deadline_webservice_changed
                ])

            cmds.setAttr("{}.machineList".format(self.instance), lock=True)
            self._rs = renderSetup.instance()
            layers = self._rs.getRenderLayers()
            if use_selection:
                print(">>> processing existing layers")
                sets = []
                for layer in layers:
                    print("  - creating set for {}:{}".format(
                        namespace, layer.name()))
                    render_set = cmds.sets(
                        n="{}:{}".format(namespace, layer.name()))
                    sets.append(render_set)
                cmds.sets(sets, forceElement=self.instance)

            # if no render layers are present, create default one with
            # asterix selector
            if not layers:
                render_layer = self._rs.createRenderLayer('Main')
                collection = render_layer.createCollection("defaultCollection")
                collection.getSelector().setPattern('*')

            renderer = cmds.getAttr(
                'defaultRenderGlobals.currentRenderer').lower()
            # handle various renderman names
            if renderer.startswith('renderman'):
                renderer = 'renderman'

            cmds.setAttr(self._image_prefix_nodes[renderer],
                         self._image_prefixes[renderer],
                         type="string")
        return self.instance

    def _deadline_webservice_changed(self):
        """Refresh Deadline served dependent options."""
        # get selected server
        webservice = self.deadline_servers[
            self.server_aliases[
                cmds.getAttr("{}.deadlineServers".format(self.instance))
            ]
        ]
        pools = self._get_deadline_pools(webservice)
        cmds.deleteAttr("{}.primaryPool".format(self.instance))
        cmds.deleteAttr("{}.secondaryPool".format(self.instance))
        cmds.addAttr(self.instance, longName="primaryPool",
                     attributeType="enum",
                     enumName=":".join(pools))
        cmds.addAttr(self.instance, longName="secondaryPool",
                     attributeType="enum",
                     enumName=":".join(["-"] + pools))

        # cmds.setAttr("{}.secondaryPool".format(self.instance), ["-"] + pools)

    def _create_render_settings(self):
        # get pools
        pools = []
        deadline_url = os.getenv("DEADLINE_REST_URL")
        if self.deadline_servers:
            for key, server in self.deadline_servers.items():
                if server == "DEADLINE_REST_URL":
                    self.deadline_servers[key] = deadline_url

            self.server_aliases = self.deadline_servers.keys()
            deadline_url = self.deadline_servers[self.server_aliases[0]]
            print("deadline servers: {}".format(self.deadline_servers))
            self.data["deadlineServers"] = self.server_aliases
        else:
            self.data["deadlineServers"] = [deadline_url]

        self.data["suspendPublishJob"] = False
        self.data["review"] = True
        self.data["extendFrames"] = False
        self.data["overrideExistingFrame"] = True
        # self.data["useLegacyRenderLayers"] = True
        self.data["priority"] = 50
        self.data["framesPerTask"] = 1
        self.data["whitelist"] = False
        self.data["machineList"] = ""
        self.data["useMayaBatch"] = False
        self.data["tileRendering"] = False
        self.data["tilesX"] = 2
        self.data["tilesY"] = 2
        self.data["convertToScanline"] = False
        self.data["useReferencedAovs"] = False
        # Disable for now as this feature is not working yet
        # self.data["assScene"] = False

        self.options = {"useSelection": False}  # Force no content
        muster_url = os.environ.get("MUSTER_REST_URL", None)
        if deadline_url and muster_url:
            self.log.error(
                "Both Deadline and Muster are enabled. " "Cannot support both."
            )
            raise RuntimeError("Both Deadline and Muster are enabled")

        if deadline_url is None:
            self.log.warning("Deadline REST API url not found.")
        else:
            pools = self._get_deadline_pools(deadline_url)
            self.data["primaryPool"] = pools
            # We add a string "-" to allow the user to not
            # set any secondary pools
            self.data["secondaryPool"] = ["-"] + pools

        if muster_url is None:
            self.log.warning("Muster REST API URL not found.")
        else:
            self.log.info(">>> Loading Muster credentials ...")
            self._load_credentials()
            self.log.info(">>> Getting pools ...")
            try:
                pools = self._get_muster_pools()
            except requests.exceptions.HTTPError as e:
                if e.startswith("401"):
                    self.log.warning("access token expired")
                    self._show_login()
                    raise RuntimeError("Access token expired")
            except requests.exceptions.ConnectionError:
                self.log.error("Cannot connect to Muster API endpoint.")
                raise RuntimeError("Cannot connect to {}".format(muster_url))
            pool_names = []
            for pool in pools:
                self.log.info("  - pool: {}".format(pool["name"]))
                pool_names.append(pool["name"])

            self.data["primaryPool"] = pool_names

    def _load_credentials(self):
        """Load Muster credentials.

        Load Muster credentials from file and set ``MUSTER_USER``,
        ``MUSTER_PASSWORD``, ``MUSTER_REST_URL`` is loaded from presets.

        Raises:
            RuntimeError: If loaded credentials are invalid.
            AttributeError: If ``MUSTER_REST_URL`` is not set.

        """
        app_dir = os.path.normpath(appdirs.user_data_dir("pype-app", "pype"))
        file_name = "muster_cred.json"
        fpath = os.path.join(app_dir, file_name)
        file = open(fpath, "r")
        muster_json = json.load(file)
        self._token = muster_json.get("token", None)
        if not self._token:
            self._show_login()
            raise RuntimeError("Invalid access token for Muster")
        file.close()
        self.MUSTER_REST_URL = os.environ.get("MUSTER_REST_URL")
        if not self.MUSTER_REST_URL:
            raise AttributeError("Muster REST API url not set")

    def _get_muster_pools(self):
        """Get render pools from Muster.

        Raises:
            Exception: If pool list cannot be obtained from Muster.

        """
        params = {"authToken": self._token}
        api_entry = "/api/pools/list"
        response = self._requests_get(self.MUSTER_REST_URL + api_entry,
                                      params=params)
        if response.status_code != 200:
            if response.status_code == 401:
                self.log.warning("Authentication token expired.")
                self._show_login()
            else:
                self.log.error(
                    ("Cannot get pools from "
                     "Muster: {}").format(response.status_code)
                )
                raise Exception("Cannot get pools from Muster")
        try:
            pools = response.json()["ResponseData"]["pools"]
        except ValueError as e:
            self.log.error("Invalid response from Muster server {}".format(e))
            raise Exception("Invalid response from Muster server")

        return pools

    def _get_deadline_pools(self, webservice):
        # type: (str) -> list
        """Get pools from Deadline.

        Args:
            webservice (str): Server url.

        Returns:
            list: Pools.

        Throws:
            RuntimeError: If deadline webservice is unreachable.

        """
        argument = "{}/api/pools?NamesOnly=true".format(webservice)
        try:
            response = self._requests_get(argument)
        except requests.exceptions.ConnectionError as exc:
            msg = 'Cannot connect to deadline web service'
            self.log.error(msg)
            six.reraise(exc, RuntimeError('{} - {}'.format(msg, exc)))
        if not response.ok:
            self.log.warning("No pools retrieved")
            return []

        return response.json()

    def _show_login(self):
        # authentication token expired so we need to login to Muster
        # again to get it. We use Pype API call to show login window.
        api_url = "{}/muster/show_login".format(
            os.environ["PYPE_REST_API_URL"])
        self.log.debug(api_url)
        login_response = self._requests_post(api_url, timeout=1)
        if login_response.status_code != 200:
            self.log.error("Cannot show login form to Muster")
            raise Exception("Cannot show login form to Muster")

    def _requests_post(self, *args, **kwargs):
        """Wrap request post method.

        Disabling SSL certificate validation if ``DONT_VERIFY_SSL`` environment
        variable is found. This is useful when Deadline or Muster server are
        running with self-signed certificates and their certificate is not
        added to trusted certificates on client machines.

        Warning:
            Disabling SSL certificate validation is defeating one line
            of defense SSL is providing and it is not recommended.

        """
        if "verify" not in kwargs:
            kwargs["verify"] = (
                False if os.getenv("PYPE_DONT_VERIFY_SSL", True) else True
            )  # noqa
        return requests.post(*args, **kwargs)

    def _requests_get(self, *args, **kwargs):
        """Wrap request get method.

        Disabling SSL certificate validation if ``DONT_VERIFY_SSL`` environment
        variable is found. This is useful when Deadline or Muster server are
        running with self-signed certificates and their certificate is not
        added to trusted certificates on client machines.

        Warning:
            Disabling SSL certificate validation is defeating one line
            of defense SSL is providing and it is not recommended.

        """
        if "verify" not in kwargs:
            kwargs["verify"] = (
                False if os.getenv("PYPE_DONT_VERIFY_SSL", True) else True
            )  # noqa
        return requests.get(*args, **kwargs)
