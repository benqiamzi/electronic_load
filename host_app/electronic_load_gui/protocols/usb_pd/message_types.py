from dataclasses import dataclass
from enum import StrEnum

from .diagnostics import ParseDiagnostic, ParseStatus
from .header import PDHeader
from .sop import SopKind


class MessageCategory(StrEnum):
    CONTROL = "control"
    DATA = "data"
    EXTENDED = "extended"


@dataclass(frozen=True, slots=True)
class MessageTypeInfo:
    category: MessageCategory
    code: int
    name: str | None
    status: ParseStatus


# USB PD R3.2 V1.1 Tables 6.5 and 6.6. Revision value 2 represents 3.x.
_CONTROL_NAMES = {
    1: "GoodCRC", 2: "GotoMin", 3: "Accept", 4: "Reject", 5: "Ping",
    6: "PS_RDY", 7: "Get_Source_Cap", 8: "Get_Sink_Cap", 9: "DR_Swap",
    10: "PR_Swap", 11: "VCONN_Swap", 12: "Wait", 13: "Soft_Reset",
    14: "Data_Reset", 15: "Data_Reset_Complete", 16: "Not_Supported",
    17: "Get_Source_Cap_Extended", 18: "Get_Status", 19: "FR_Swap",
    20: "Get_PPS_Status", 21: "Get_Country_Codes", 22: "Get_Sink_Cap_Extended",
    23: "Get_Source_Info", 24: "Get_Revision",
}
_DATA_NAMES = {
    1: "Source_Capabilities", 2: "Request", 3: "BIST", 4: "Sink_Capabilities",
    5: "Battery_Status", 6: "Alert", 7: "Get_Country_Info", 8: "Enter_USB",
    9: "EPR_Request", 10: "EPR_Mode", 11: "Source_Info", 12: "Revision",
    15: "Vendor_Defined",
}
_CONTROL_CABLE_CAPABLE = {1, 3, 4, 13, 16, 18, 24}
_DATA_CABLE_CAPABLE = {3, 8, 12, 15}


def classify_message(
    header: PDHeader, sop: SopKind,
) -> tuple[MessageTypeInfo, ParseDiagnostic | None]:
    """Classify a Header using the message category, wire revision and SOP."""
    code = header.message_type
    if header.extended:
        return MessageTypeInfo(MessageCategory.EXTENDED, code, None, ParseStatus.UNSUPPORTED), None
    if header.num_data_objects == 0:
        category = MessageCategory.CONTROL
        name = _CONTROL_NAMES.get(code)
        revision_3 = code >= 14
        cable_capable = code in _CONTROL_CABLE_CAPABLE
    else:
        category = MessageCategory.DATA
        name = _DATA_NAMES.get(code)
        revision_3 = 5 <= code <= 12
        cable_capable = code in _DATA_CABLE_CAPABLE

    if name is None:
        return MessageTypeInfo(category, code, None, ParseStatus.UNKNOWN), ParseDiagnostic(
            "message", "unknown_message_type", f"Unknown {category} message type {code}."
        )
    if header.spec_revision == 0 and not (category == MessageCategory.CONTROL and code == 1):
        return MessageTypeInfo(category, code, name, ParseStatus.UNSUPPORTED), ParseDiagnostic(
            "message", "legacy_revision", "USB PD Revision 1.0 semantics are outside this decoder."
        )
    if (revision_3 and header.spec_revision < 2) or (sop != SopKind.SOP and not cable_capable):
        return MessageTypeInfo(category, code, name, ParseStatus.INVALID), ParseDiagnostic(
            "message", "message_context", f"{name} is not defined for this SOP or revision."
        )
    if category == MessageCategory.CONTROL and code in (2, 5) and header.spec_revision == 2:
        return MessageTypeInfo(category, code, name, ParseStatus.UNSUPPORTED), ParseDiagnostic(
            "message", "deprecated_message", f"{name} is deprecated in the protocol baseline."
        )
    return MessageTypeInfo(category, code, name, ParseStatus.VALID), None
