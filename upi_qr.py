import segno


class UPIQRGenerator:
    def __init__(self, upi_id: str, payee_name: str, currency: str = "INR"):
        """
        INITIALISE THE UPI QR GENERATOR
        :param upi_id: EG: 1234567890@upi
        :param payee_name: Lorem ipsum dolor sit amet
        :param currency: INR
        """
        self.upi_id = upi_id
        self.payee_name = payee_name
        self.currency = currency

    def build_upi_url(self, amount: float = None):
        """
        Build the UPI URL according to the official documentation
        :param amount: could be none as well, just give the payment address
        :return:
        """
        url = f"upi://pay?pa={self.upi_id}&pn={self.payee_name}&cu={self.currency}"
        if amount:
            url += f"&am={amount}"
        return url

    def generate_segno(self, amount: float = None):
        """
        Generate the QR code as a SEGNO QR object
        :param amount:
        :return:
        """
        upi_url = self.build_upi_url(amount)
        return segno.make(upi_url)

    def generate_qrcode(self, amount: float = None, kind: str = 'svg') -> str:
        """
        Return the QR as different data objects and types
        :param amount:
        :param kind:
        :return:
        """
        qr = self.generate_segno(amount)
        if kind == "svg":
            return qr.svg_data_uri(scale=5)
        elif kind == "png":
            return qr.png_data_uri(scale=5)
        elif kind == "jpg":
            return qr.png_data_uri(scale=5)
        elif kind == "jpeg":
            return qr.png_data_uri(scale=5)
        elif kind == "json":
            return qr.json_data_uri(scale=5)
        elif kind == "xml":
            return qr.xml_data_uri(scale=5)
        else:
            raise ValueError("Unknown kind {}".format(kind),
                             "Supported kinds: 'svg', 'png', 'jpg', 'jpeg', 'json', 'xml'")

