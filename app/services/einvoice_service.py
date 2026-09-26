"""GST e-Invoice (IRP) support. serialize_to_inv01() builds the standard
INV-01 JSON schema from a voucher; the actual IRP submission is left as an
integration point (attach_irn) so a live NIC/GSP client can be plugged in
later without touching the schema logic."""

from typing import Any


def serialize_to_inv01(voucher: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    items = voucher.get("items", [])
    item_list = []
    for idx, item in enumerate(items, start=1):
        qty = float(item.get("qty", 0) or 0)
        rate = float(item.get("price", 0) or 0)
        taxable = float(item.get("taxable", qty * rate) or 0)
        gst_rate = float(item.get("gstRate", 18.0) or 18.0)
        cgst = float(item.get("cgst", 0) or 0)
        sgst = float(item.get("sgst", 0) or 0)
        igst = float(item.get("igst", 0) or 0)
        item_list.append(
            {
                "SlNo": str(idx),
                "PrdDesc": str(item.get("item", "Item")),
                "IsServc": "N",
                "HsnCd": str(item.get("hsn", "999999")),
                "Qty": qty,
                "Unit": str(item.get("unit", "NOS")),
                "UnitPrice": rate,
                "TotAmt": taxable,
                "AssAmt": taxable,
                "GstRt": gst_rate,
                "IgstAmt": igst,
                "CgstAmt": cgst,
                "SgstAmt": sgst,
                "TotItemVal": taxable + cgst + sgst + igst,
            }
        )

    return {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N", "IgstOnIntra": "N"},
        "DocDtls": {
            "Typ": "INV",
            "No": str(voucher.get("voucherNumber", "")),
            "Dt": str(voucher.get("date", "")),
        },
        "SellerDtls": {
            "Gstin": str(company.get("gstin", "")),
            "LglNm": str(company.get("companyName", "")),
            "Addr1": str(company.get("address", "")),
            "Loc": str(company.get("city", "")),
            "Pin": int(company.get("pincode", 110001) or 110001),
            "Stcd": str(company.get("stateCode", "")),
        },
        "BuyerDtls": {
            "Gstin": str(voucher.get("partyGstin", "")),
            "LglNm": str(voucher.get("party", "")),
            "Pos": str(voucher.get("pos", "")),
            "Addr1": str(voucher.get("partyAddress", "")),
            "Loc": str(voucher.get("partyCity", "")),
            "Pin": int(voucher.get("partyPincode", 110001) or 110001),
            "Stcd": str(voucher.get("partyStateCode", "")),
        },
        "ItemList": item_list,
        "ValDtls": {
            "AssVal": float(voucher.get("subTotal", 0) or 0),
            "CgstVal": float(voucher.get("cgst", 0) or 0),
            "SgstVal": float(voucher.get("sgst", 0) or 0),
            "IgstVal": float(voucher.get("igst", 0) or 0),
            "RndOffAmt": float(voucher.get("roundOff", 0) or 0),
            "TotInvVal": float(voucher.get("grandTotal", 0) or 0),
        },
    }