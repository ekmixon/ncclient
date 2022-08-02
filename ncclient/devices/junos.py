"""
Handler for Juniper device specific information.

Note that for proper import, the classname has to be:

    "<Devicename>DeviceHandler"

...where <Devicename> is something like "Default", "Junos", etc.

All device-specific handlers derive from the DefaultDeviceHandler, which implements the
generic information needed for interaction with a Netconf server.

"""
import logging
import re

from lxml import etree
from lxml.etree import QName

from ncclient.operations.retrieve import GetSchemaReply
from .default import DefaultDeviceHandler
from ncclient.operations.third_party.juniper.rpc import GetConfiguration, LoadConfiguration, CompareConfiguration
from ncclient.operations.third_party.juniper.rpc import ExecuteRpc, Command, Reboot, Halt, Commit, Rollback
from ncclient.operations.rpc import RPCError
from ncclient.xml_ import to_ele, replace_namespace, BASE_NS_1_0, NETCONF_MONITORING_NS
from ncclient.transport.third_party.junos.parser import JunosXMLParser
from ncclient.transport.parser import DefaultXMLParser
from ncclient.transport.parser import SAXParserHandler


logger = logging.getLogger(__name__)


class JunosDeviceHandler(DefaultDeviceHandler):
    """
    Juniper handler for device specific information.

    """

    def __init__(self, device_params):
        super(JunosDeviceHandler, self).__init__(device_params)
        self.__reply_parsing_error_transform_by_cls = {
            GetSchemaReply: fix_get_schema_reply
        }

    def add_additional_operations(self):
        return {
            "rpc": ExecuteRpc,
            "get_configuration": GetConfiguration,
            "load_configuration": LoadConfiguration,
            "compare_configuration": CompareConfiguration,
            "command": Command,
            "reboot": Reboot,
            "halt": Halt,
            "commit": Commit,
            "rollback": Rollback,
        }

    def perform_qualify_check(self):
        return False

    def handle_raw_dispatch(self, raw):
        if 'routing-engine' in raw:
            raw = re.sub(r'<ok/>', '</routing-engine>\n<ok/>', raw)
            return raw
        elif re.search(r'<rpc-reply>.*?</rpc-reply>.*</hello>?', raw, re.M | re.S):
            if errs := re.findall(r'<rpc-error>.*?</rpc-error>', raw, re.M | re.S):
                add_ns = """
                        <xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
                          <xsl:output indent="yes"/>
                            <xsl:template match="*">
                            <xsl:element name="{local-name()}" namespace="urn:ietf:params:xml:ns:netconf:base:1.0">
                            <xsl:apply-templates select="@*|node()"/>
                            </xsl:element>
                          </xsl:template>
                        </xsl:stylesheet>"""
                err_list = []
                for err in errs:
                    doc = etree.ElementTree(etree.XML(err))
                    # Adding namespace using xslt
                    xslt = etree.XSLT(etree.XML(add_ns))
                    transformed_xml = etree.XML(etree.tostring(xslt(doc)))
                    err_list.append(RPCError(transformed_xml))
                return RPCError(to_ele("<rpc-reply>"+''.join(errs)+"</rpc-reply>"), err_list)
        else:
            return False

    def handle_connection_exceptions(self, sshsession):
        c = sshsession._channel = sshsession._transport.open_channel(
            kind="session")
        c.set_name(f"netconf-command-{str(sshsession._channel_id)}")
        c.exec_command("xml-mode netconf need-trailer")
        return True

    def reply_parsing_error_transform(self, reply_cls):
        # return transform function if found, else None
        return self.__reply_parsing_error_transform_by_cls.get(reply_cls)

    def transform_reply(self):
        reply = '''<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
        <xsl:output method="xml" indent="no"/>

        <xsl:template match="/|comment()|processing-instruction()">
            <xsl:copy>
                <xsl:apply-templates/>
            </xsl:copy>
        </xsl:template>

        <xsl:template match="*">
            <xsl:element name="{local-name()}">
                <xsl:apply-templates select="@*|node()"/>
            </xsl:element>
        </xsl:template>

        <xsl:template match="@*">
            <xsl:attribute name="{local-name()}">
                <xsl:value-of select="."/>
            </xsl:attribute>
        </xsl:template>
        </xsl:stylesheet>
        '''
        import sys
        return reply if sys.version < '3' else reply.encode('UTF-8')

    def get_xml_parser(self, session):
        if not self.device_params.get('use_filter', False):
            return DefaultXMLParser(session)
        if l := session.get_listener_instance(SAXParserHandler):
            session.remove_listener(l)
            del l
        session.add_listener(SAXParserHandler(session))
        return JunosXMLParser(session)


def fix_get_schema_reply(root):
    # Workaround for wrong namespace of the data elem
    # (issue with some Junos versions, might be corrected by Juniper at some point)

    # get the data element, by local-name
    data_elems = root.xpath('/nc:rpc-reply/*[local-name()="data"]', namespaces={'nc': BASE_NS_1_0})

    if len(data_elems) != 1:
        return  # Will not alter unexpected content

    data_el = data_elems[0]
    namespace = QName(data_el).namespace

    if namespace == BASE_NS_1_0:
        # With the default netconf setting, we may get "{BASE_NS_1_0}data"; warn and fix it
        logger.warning("The device seems to run non-rfc compliant netconf. You may want to "
                       "configure: 'set system services netconf rfc-compliant'")
        replace_namespace(data_el, old_ns=BASE_NS_1_0, new_ns=NETCONF_MONITORING_NS)
    elif namespace is None:
        # With 'set system services netconf rfc-compliant' we may get "data" (no namespace); fix it
        # There is no default xmlns and the data el is <data xmlns:ncm="NETCONF_MONITORING_NS">
        replace_namespace(data_el, old_ns=None, new_ns=NETCONF_MONITORING_NS)
