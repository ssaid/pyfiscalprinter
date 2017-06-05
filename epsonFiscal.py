# -*- coding: iso-8859-1 -*-
import string
import types
import logging
import unicodedata
from fiscalGeneric import PrinterInterface, PrinterException
import epsonFiscalDriver

class FiscalPrinterError(Exception):
    pass


class FileDriver:

    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, "w")

    def sendCommand(self, command, parameters):
        self.file.write("Command: %d, Parameters: %s\n" % (command, parameters))
        return ["BLA", "BLA", "BLA", "BLA", "BLA", "BLA", "BLA", "BLA", ]

    def close(self):
        self.file.close()


def formatText(text):
    asciiText = unicodedata.normalize('NFKD', unicode(text)).encode('ASCII', 'ignore')
    asciiText = asciiText.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return asciiText


class DummyDriver:

    def __init__(self):
        try:
            self.number = int(raw_input("Ingrese el número de la última factura: "))
        except EOFError:
            # iniciar desde 0 (ejecutando sin stdin)
            self.number = 0

    def close(self):
        pass

    def sendCommand(self, commandNumber, parameters, skipStatusErrors):
        ##raise RuntimeError("saraza1")
##        if commandNumber in EpsonPrinter.CMD_CLOSE_FISCAL_RECEIPT:
##            #raise RuntimeError("saraza")
##        else:
##            pass
        return ["00", "00", "", "", str(self.number), "", str(self.number)] + [str(self.number)] * 11


class EpsonPrinter(PrinterInterface):
    DEBUG = True

    CMD_OPEN_FISCAL_RECEIPT = 0x40
    CMD_OPEN_BILL_TICKET = 0x60
##    CMD_PRINT_TEXT_IN_FISCAL = (0x41, 0x61)
    CMD_PRINT_TEXT_IN_FISCAL = 0x41
    CMD_PRINT_LINE_ITEM = (0x42, 0x62)
    CMD_PRINT_SUBTOTAL = (0x43, 0x63)
    CMD_ADD_PAYMENT = (0x44, 0x64)
    CMD_CLOSE_FISCAL_RECEIPT = (0x45, 0x65)
    CMD_DAILY_CLOSE = 0x39
    CMD_STATUS_REQUEST = 0x2a

    CMD_OPEN_DRAWER = 0x7b

    CMD_SET_HEADER_TRAILER = 0x5d

    CMD_OPEN_NON_FISCAL_RECEIPT = 0x48
    CMD_PRINT_NON_FISCAL_TEXT = 0x49
    CMD_CLOSE_NON_FISCAL_RECEIPT = 0x4a

    CURRENT_DOC_TICKET = 1
    CURRENT_DOC_BILL_TICKET = 2
    CURRENT_DOC_CREDIT_TICKET = 4
    CURRENT_DOC_NON_FISCAL = 3

    models = ["tickeadoras", "epsonlx300+", "tm-220-af"]

    def __init__(self, deviceFile=None, speed=9600, host=None, port=None, dummy=False, model=None):
        try:
            if dummy:
                self.driver = DummyDriver()
            elif host:
                self.driver = epsonFiscalDriver.EpsonFiscalDriverProxy(host, port)
            else:
                deviceFile = deviceFile or 0
                self.driver = epsonFiscalDriver.EpsonFiscalDriver(deviceFile, speed)
            #self.driver = FileDriver( "/home/gnarvaja/Desktop/fiscal.txt" )
        except Exception, e:
            raise FiscalPrinterError("Imposible establecer comunicación.", e)
        if not model:
            self.model = "tickeadoras"
        else:
            self.model = model
        self._currentDocument = None
        self._currentDocumentType = None

    def _sendCommand(self, commandNumber, parameters, skipStatusErrors=False):
        print "_sendCommand", commandNumber, parameters
        try:
            logging.getLogger().info("sendCommand: SEND|0x%x|%s|%s" % (commandNumber,
                skipStatusErrors and "T" or "F",
                                                                     str(parameters)))
            return self.driver.sendCommand(commandNumber, parameters, skipStatusErrors)
        except epsonFiscalDriver.PrinterException, e:
            logging.getLogger().error("epsonFiscalDriver.PrinterException: %s" % str(e))
            raise PrinterException("Error de la impresora fiscal: " + str(e))

    def receipt(self, rdict):
        """
        This will be called when the endpoint print_xml_receipt is called.
        """
        import pprint
        pprint.pprint(rdict)
        printer = self
# Creamos un ticket
        client = rdict['receipt']['client']
        if client:
            client_name = client['name']
        else:
            client_name = 'Consumidor Final'
        if not client or not client['fp']:  # Consumidor Final: FC/NC B
            invoice_denomination = "B"
            customer_iva_type = printer.IVA_TYPE_CONSUMIDOR_FINAL
            customer_name = client_name
            customer_doc = None
            customer_address = ""
            customer_doc_type = None
        else:  # Ask the fiscal position
            fp_str = client['fp'][1]
            if fp_str == 'RI':
                invoice_denomination = "A"
                customer_iva_type = printer.IVA_TYPE_RESPONSABLE_INSCRIPTO
                customer_name = client_name
                customer_doc = client['vat']
                customer_address = client['address']
                customer_doc_type = printer.DOC_TYPE_CUIT
            else:  # != RI
                invoice_denomination = "B"
                customer_iva_type = printer.IVA_TYPE_CONSUMIDOR_FINAL
                customer_name = client_name
                customer_doc = None
                customer_address = ""
                customer_doc_type = None

        subtotal = rdict['receipt']['subtotal']
        if subtotal > 0:
            invoice_type = 'FC'
        elif subtotal < 0:
            invoice_type = 'NC'
        else:
            print 'Never should enter here!'
            sys.exit(1)

        if invoice_type == "FC":
            open_res = printer.openBillTicket(invoice_denomination, customer_name, customer_address, customer_doc, customer_doc_type, customer_iva_type)
        elif invoice_type == "NC":
            open_res = printer.openBillCreditTicket(invoice_denomination, customer_name, customer_address, customer_doc, customer_doc_type, customer_iva_type)
        elif invoice_type == "ND":
            pass
        else:
            print "Documento %s no reconocido" % invoice_type
            sys.exit(-1)

        # lines = [{
        #     'description': 'Item1',
        #     'qty': 10,
        #     'price': 25.0,
        #     'tax': 21.0}]

        lines = rdict['receipt']['orderlines']

        for line in lines:
            print line
            qty = abs(line['quantity'])
            price_with_tax = abs(line['price_with_tax'])
            # As we don't have the tax for the line
            # price_without_tax = abs(line['price_without_tax'])
            # tax = ((price_with_tax / float(price_without_tax)) - 1) * 100
            # tax_r = round(Decimal(tax), 2)
            tax_r = line['vat_percent']
            printer.addItem(line['product_name'], qty, price_with_tax / qty, tax_r, discount=0.0, discountDescription="", negative=False)

#subtotal_lines += Decimal(line['subtotal'])
#subtotal_lines_discount += Decimal(line['subtotal_discount'])
#
## Agregamos percepciones si las hay
#if self.customer_percep:
#if not self.posConf.debug:
#    printer.addPerception("Percep IIBB ARBA", float(self.perception_amount))
#
## Descuento General
#if self.discount != Decimal("0.0"):
## Calculamos el descuento
#discount_amount = subtotal_lines - subtotal_lines_discount
#if not self.posConf.debug:
#    if discount_amount:
#        printer.addAdditional("DESCUENTO", float(discount_amount), None, negative=True)

# Cobros
        paymentlines = rdict['receipt']['paymentlines']
        for payment in paymentlines:
            printer.addPayment(payment['journal'], payment['amount'])

        number_to = printer.closeDocument()  # WARNING: printer in anormal state may print ticket but here raise an printerException. Thus we return from here with None.
        print "Ticket printed: ", number_to
        return number_to

    def parse_status(self, res):
        assert type(res) is list, 'res must be a list'
        # Guardamos las respuestas
        d = {}
        print res
        # TODO: Review values from here, they are not coincident from what printer reports.
        printer_status_response = int(res[0], 16)
        fiscal_status_response = int(res[1], 16)
        d['last_inv_B_C_doc'] = int(res[2])
        d['aux_status'] = int(res[3], 16)
        d['last_inv_A_doc'] = int(res[4], 16)
        d['document_status'] = int(res[5], 16)
        d['last_nc_B_C_doc'] = int(res[6], 16)
        d['last_nc_A_doc'] = int(res[7], 16)

        # Status fiscal
        if ((1 << 0) & fiscal_status_response) == (1 << 0):
            status_fiscal = "Error en chequeo de memoria fiscal. \n"
#                    "Al encenderse la impresora se produjo un error en el " \
#                    "checksum.  La impresora no funcionara."
        elif ((1 << 1) & fiscal_status_response) == (1 << 1):
            status_fiscal = "Error en chequeo de memoria de trabajo.\n"
#                    "Al encenderse la impresora se produjo un error en el " \
#                    "checksum.  La impresora no funcionara."
        elif ((1 << 3) & fiscal_status_response) == (1 << 3):
            status_fiscal = "Comando desconocido.\n"
#                    "El comando recibido no fue reconocido."
        elif ((1 << 4) & fiscal_status_response) == (1 << 4):
            status_fiscal = "Datos no válidos en un campo.\n"
#                    "Uno de los campos del comando recibido tiene datos no " \
#                    "válidos por ejemplo, datos no numéricos en un campo numérico)."
        elif ((1 << 5) & fiscal_status_response) == (1 << 5):
            status_fiscal = "Comando no válido para el estado fiscal actual.\n "
#                "Se ha recibido un comando que no es válido en el estado " \
#                "actual del controlador (por ejemplo, abrir un recibo no " \
#                "fiscal cuando se encuentra abierto un recibo fiscal)."

        elif ((1 << 6) & fiscal_status_response) == (1 << 6):
            status_fiscal = "Desborde del Total.\n"
#                    "El acumulador de una transacción, del total diario o " \
#                    "del IVA se desbordará a raíz de un comando recibido." \
#                    "El comando no es ejecutado. Este bit debe ser monitoreado " \
#                    "por el host para emitir un aviso de error."

        elif ((1 << 7) & fiscal_status_response) == (1 << 7):
            status_fiscal = "Memoria fiscal llena, bloqueada o dada de baja.\n"
#                "En caso de que la memoria fiscal esté llena, bloqueada o " \
#                "dada de baja, no se per mite abrir un comprobante fiscal."

        elif ((1 << 8) & fiscal_status_response) == (1 << 8):
            status_fiscal = "Memoria fiscal a punto de llenarse.\n"
#                "La memoria fiscal tiene 30 o menos registros libres." \
#                "Este bit debe ser monitoreado por el host para emitir " \
#                "el correspondiente aviso."
        elif ((1 << 9) & fiscal_status_response) == (1 << 9):
            status_fiscal = "Terminal fiscal certificada.\n"
#                "Indica que la impresora ha sido inicializada."
        elif ((1 << 10) & fiscal_status_response) == (1 << 10):
            status_fiscal = "Terminal fiscal certificada.\n"
#                "Indica que la impresora ha sido inicializada."

        elif ((1 << 11) & fiscal_status_response) == (1 << 11):
            status_fiscal = "Error en ingreso de fecha.\n"
#                "Se ha ingresado una fecha no válida." \
#                "Para volver al bit a 0 debe ingresarse una fecha válida."

        elif ((1 << 12) & fiscal_status_response) == (1 << 12):
            status_fiscal = "Documento fiscal abierto.\n"
#                "Este bit se encuentra en 1 siempre que un documento " \
#                "fiscal (factura, recibo oficial o nota de crédito) se " \
#                "encuentra abierto."

        elif ((1 << 13) & fiscal_status_response) == (1 << 13):
            status_fiscal = "Documento abierto.\n"
#                "Este bit se encuentra en 1 siempre que un documento " \
#                "(fiscal, no fiscal o no fiscal homologado) se encuentra abierto."

        elif ((1 << 14) & fiscal_status_response) == (1 << 14):
            status_fiscal = "STATPRN activado.\n"
#                "Este bit se encuentra en 1 cuando se intenta enviar " \
#                "un comando estando activado el STATPRN. El comando es rechazado."

        elif ((1 << 3) & fiscal_status_response) == (1 << 3):
            status_fiscal = "OR lógico de los bits 0 a 8.\n"
#                "Este bit se encuentra en 1 siempre que alguno de los bits " \
#                "mencionados se encuentre en 1."

        if ((1 << 0) & printer_status_response) == (1 << 0):
            status_printer = "Impresora Ocupada"
        elif ((1 << 2) & printer_status_response) == (1 << 2):
            status_printer = "Error de Impresora."
        elif ((1 << 3) & printer_status_response) == (1 << 3):
            status_printer = "Impresora Offline"
        elif ((1 << 4) & printer_status_response) == (1 << 4):
            status_printer = "Falta papel"
        elif ((1 << 5) & printer_status_response) == (1 << 5):
            status_printer = "Falta papel de tickets"
        elif ((1 << 6) & printer_status_response) == (1 << 6):
            status_printer = "Buffer de Impresora lleno"
        elif ((1 << 7) & printer_status_response) == (1 << 7):
            status_printer = "Impresora lista"
        elif ((1 << 8) & printer_status_response) == (1 << 8):
            status_printer = "Tapa de Impresora Abierta"

        d['statusPrinter'] = status_printer
        d['statusFiscal'] = status_fiscal

        return status_printer, status_fiscal, d

    def openNonFiscalReceipt(self):
        status = self._sendCommand(self.CMD_OPEN_NON_FISCAL_RECEIPT, [])
        self._currentDocument = self.CURRENT_DOC_NON_FISCAL
        self._currentDocumentType = None
        return status

    def printNonFiscalText(self, text):
        return self._sendCommand(self.CMD_PRINT_NON_FISCAL_TEXT, [formatText(text[:40] or " ")])

    ivaTypeMap = {
        PrinterInterface.IVA_TYPE_RESPONSABLE_INSCRIPTO: 'I',
        PrinterInterface.IVA_TYPE_RESPONSABLE_NO_INSCRIPTO: 'R',
        PrinterInterface.IVA_TYPE_EXENTO: 'E',
        PrinterInterface.IVA_TYPE_NO_RESPONSABLE: 'N',
        PrinterInterface.IVA_TYPE_CONSUMIDOR_FINAL: 'F',
        PrinterInterface.IVA_TYPE_RESPONSABLE_NO_INSCRIPTO_BIENES_DE_USO: 'R',
        PrinterInterface.IVA_TYPE_RESPONSABLE_MONOTRIBUTO: 'M',
        PrinterInterface.IVA_TYPE_MONOTRIBUTISTA_SOCIAL: 'M',
        PrinterInterface.IVA_TYPE_PEQUENIO_CONTRIBUYENTE_EVENTUAL: 'F',
        PrinterInterface.IVA_TYPE_PEQUENIO_CONTRIBUYENTE_EVENTUAL_SOCIAL: 'F',
        PrinterInterface.IVA_TYPE_NO_CATEGORIZADO: 'F',
    }

    ADDRESS_SIZE = 30

    def _setHeaderTrailer(self, line, text):
        self._sendCommand(self.CMD_SET_HEADER_TRAILER, (str(line), text))

    def setHeader(self, header=None):
        "Establecer encabezados"
        if not header:
            header = []
        line = 3
        for text in (header + [chr(0x7f)]*3)[:3]: # Agrego chr(0x7f) (DEL) al final para limpiar las
                                                  # líneas no utilizadas
            self._setHeaderTrailer(line, text)
            line += 1

    def setTrailer(self, trailer=None):
        "Establecer pie"
        if not trailer:
            trailer = []
        line = 11
        for text in (trailer + [chr(0x7f)] * 9)[:9]:
            self._setHeaderTrailer(line, text)
            line += 1

    def openBillCreditTicket(self, type, name, address, doc, docType, ivaType, reference="NC"):
        return self._openBillCreditTicket(type, name, address, doc, docType, ivaType, isCreditNote=True)

    def openBillTicket(self, type, name, address, doc, docType, ivaType):
        return self._openBillCreditTicket(type, name, address, doc, docType, ivaType, isCreditNote=False)

    def _openBillCreditTicket(self, type, name, address, doc, docType, ivaType, isCreditNote,
            reference=None):
        if not doc or filter(lambda x: x not in string.digits + "-.", doc or "") or not \
                docType in self.docTypeNames:
            doc, docType = "", ""
        else:
            doc = doc.replace("-", "").replace(".", "")
            docType = self.docTypeNames[docType]
        self._type = type
        if self.model == "epsonlx300+":
            parameters = [isCreditNote and "N" or "F", # Por ahora no soporto ND, que sería "D"
                "C",
                type, # Tipo de FC (A/B/C)
                "1",   # Copias - Ignorado
                "P",   # "P" la impresora imprime la lineas(hoja en blanco) o "F" preimpreso
                "17",   # Tamaño Carac - Ignorado
                "I",   # Responsabilidad en el modo entrenamiento - Ignorado
                self.ivaTypeMap.get(ivaType, "F"),   # Iva Comprador
                formatText(name[:40]), # Nombre
                formatText(name[40:80]), # Segunda parte del nombre - Ignorado
                formatText(docType) or (isCreditNote and "-" or ""),
                 # Tipo de Doc. - Si es NC obligado pongo algo
                doc or (isCreditNote and "-" or ""), # Nro Doc - Si es NC obligado pongo algo
                "N", # No imprime leyenda de BIENES DE USO
                formatText(address[:self.ADDRESS_SIZE] or "-"), # Domicilio
                formatText(address[self.ADDRESS_SIZE:self.ADDRESS_SIZE * 2]), # Domicilio 2da linea
                formatText(address[self.ADDRESS_SIZE * 2:self.ADDRESS_SIZE * 3]), # Domicilio 3ra linea
                (isCreditNote or self.ivaTypeMap.get(ivaType, "F") != "F") and "-" or "",
                # Remito primera linea - Es obligatorio si el cliente no es consumidor final
                "", # Remito segunda linea
                "C", # No somos una farmacia
                ]
        else:
            parameters = [isCreditNote and "M" or "T", # Ticket NC o Factura
                "C",  # Tipo de Salida - Ignorado
                type, # Tipo de FC (A/B/C)
                "1",   # Copias - Ignorado
                "P",   # Tipo de Hoja - Ignorado
                "17",   # Tamaño Carac - Ignorado
                "E",   # Responsabilidad en el modo entrenamiento - Ignorado
                self.ivaTypeMap.get(ivaType, "F"),   # Iva Comprador
                formatText(name[:40]), # Nombre
                formatText(name[40:80]), # Segunda parte del nombre - Ignorado
                formatText(docType) or (isCreditNote and "-" or ""),
                 # Tipo de Doc. - Si es NC obligado pongo algo
                doc or (isCreditNote and "-" or ""), # Nro Doc - Si es NC obligado pongo algo
                "N", # No imprime leyenda de BIENES DE USO
                formatText(address[:self.ADDRESS_SIZE] or "-"), # Domicilio
                formatText(address[self.ADDRESS_SIZE:self.ADDRESS_SIZE * 2]), # Domicilio 2da linea
                formatText(address[self.ADDRESS_SIZE * 2:self.ADDRESS_SIZE * 3]), # Domicilio 3ra linea
                (isCreditNote or self.ivaTypeMap.get(ivaType, "F") != "F") and "-" or "",
                # Remito primera linea - Es obligatorio si el cliente no es consumidor final
                "", # Remito segunda linea
                "C", # No somos una farmacia
                ]
        if isCreditNote:
            self._currentDocument = self.CURRENT_DOC_CREDIT_TICKET
        else:
            self._currentDocument = self.CURRENT_DOC_BILL_TICKET
        # guardo el tipo de FC (A/B/C)
        self._currentDocumentType = type
        return self._sendCommand(self.CMD_OPEN_BILL_TICKET, parameters)

    def _getCommandIndex(self):
        if self._currentDocument == self.CURRENT_DOC_TICKET:
            return 0
        elif self._currentDocument in (self.CURRENT_DOC_BILL_TICKET, self.CURRENT_DOC_CREDIT_TICKET):
            return 1
        elif self._currentDocument == self.CURRENT_DOC_NON_FISCAL:
            return 2
        raise "Invalid currentDocument"

    def openTicket(self, defaultLetter='B'):
        if self.model == "epsonlx300+":
            return self.openBillTicket(defaultLetter, "CONSUMIDOR FINAL", "", None, None,
                self.IVA_TYPE_CONSUMIDOR_FINAL)
        else:
            self._sendCommand(self.CMD_OPEN_FISCAL_RECEIPT, ["C"])
            self._currentDocument = self.CURRENT_DOC_TICKET

    def openDrawer(self):
        self._sendCommand(self.CMD_OPEN_DRAWER, [])

    def closeDocument(self):
        if self._currentDocument == self.CURRENT_DOC_TICKET:
            reply = self._sendCommand(self.CMD_CLOSE_FISCAL_RECEIPT[self._getCommandIndex()], ["T"])
            return reply[2]
        if self._currentDocument == self.CURRENT_DOC_BILL_TICKET:
            reply = self._sendCommand(self.CMD_CLOSE_FISCAL_RECEIPT[self._getCommandIndex()],
                [self.model == "epsonlx300+" and "F" or "T", self._type, "FINAL"])
            del self._type
            return reply[2]
        if self._currentDocument == self.CURRENT_DOC_CREDIT_TICKET:
            reply = self._sendCommand(self.CMD_CLOSE_FISCAL_RECEIPT[self._getCommandIndex()],
                [self.model == "epsonlx300+" and "N" or "M", self._type, "FINAL"])
            del self._type
            return reply[2]
        if self._currentDocument in (self.CURRENT_DOC_NON_FISCAL, ):
            return self._sendCommand(self.CMD_CLOSE_NON_FISCAL_RECEIPT, ["T"])
        raise NotImplementedError

    def cancelDocument(self):
        if self._currentDocument in (self.CURRENT_DOC_TICKET, self.CURRENT_DOC_BILL_TICKET,
                self.CURRENT_DOC_CREDIT_TICKET):
            status = self._sendCommand(self.CMD_ADD_PAYMENT[self._getCommandIndex()], ["Cancelar", "0", 'C'])
            return status
        if self._currentDocument in (self.CURRENT_DOC_NON_FISCAL, ):
            self.printNonFiscalText("CANCELADO")
            return self.closeDocument()
        raise NotImplementedError

    def addItem(self, description, quantity, price, iva, discount, discountDescription, negative=False):
        if type(description) in types.StringTypes:
            description = [description]
        if negative:
            sign = 'R'
        else:
            sign = 'M'
        quantityStr = str(int(quantity * 1000))
        if self.model == "epsonlx300+":
            bultosStr = str(int(quantity))
        else:
            bultosStr = "0" * 5  # No se usa en TM220AF ni TM300AF ni TMU220AF
        if self._currentDocumentType != 'A':
            # enviar con el iva incluido
            priceUnitStr = str(int(round(price * 100, 0)))
        else:
            if self.model == "tm-220-af":
                # enviar sin el iva (factura A)
                priceUnitStr =  "%0.4f" % (price / ((100.0 + iva) / 100.0))
            else:
                # enviar sin el iva (factura A)
                priceUnitStr = str(int(round((price / ((100 + iva) / 100)) * 100, 0)))
        ivaStr = str(int(iva * 100))
        extraparams = self._currentDocument in (self.CURRENT_DOC_BILL_TICKET,
            self.CURRENT_DOC_CREDIT_TICKET) and ["", "", ""] or []
        if self._getCommandIndex() == 0:
            for d in description[:-1]:
                self._sendCommand(self.CMD_PRINT_TEXT_IN_FISCAL,
                                   [formatText(d)[:20]])
        reply = self._sendCommand(self.CMD_PRINT_LINE_ITEM[self._getCommandIndex()],
                          [formatText(description[-1][:20]),
                            quantityStr, priceUnitStr, ivaStr, sign, bultosStr, "0" * 8] + extraparams)
        if discount:
            discountStr = str(int(discount * 100))
            self._sendCommand(self.CMD_PRINT_LINE_ITEM[self._getCommandIndex()],
                [formatText(discountDescription[:20]), "1000",
                  discountStr, ivaStr, 'R', "0", "0"] + extraparams)
        return reply

    def addPayment(self, description, payment):
        paymentStr = str(int(payment * 100))
        status = self._sendCommand(self.CMD_ADD_PAYMENT[self._getCommandIndex()],
                                   [formatText(description)[:20], paymentStr, 'T'])
        return status

    def addAdditional(self, description, amount, iva, negative=False):
        """Agrega un adicional a la FC.
            @param description  Descripción
            @param amount       Importe (sin iva en FC A, sino con IVA)
            @param iva          Porcentaje de Iva
            @param negative True->Descuento, False->Recargo"""
        if negative:
            sign = 'R'
        else:
            sign = 'M'
        quantityStr = "1000"
        bultosStr = "0"
        priceUnit = amount
        if self._currentDocumentType != 'A':
            # enviar con el iva incluido
            priceUnitStr = str(int(round(priceUnit * 100, 0)))
        else:
            # enviar sin el iva (factura A)
            priceUnitStr = str(int(round((priceUnit / ((100 + iva) / 100)) * 100, 0)))
        ivaStr = str(int(iva * 100))
        extraparams = self._currentDocument in (self.CURRENT_DOC_BILL_TICKET,
            self.CURRENT_DOC_CREDIT_TICKET) and ["", "", ""] or []
        reply = self._sendCommand(self.CMD_PRINT_LINE_ITEM[self._getCommandIndex()],
                          [formatText(description[:20]),
                            quantityStr, priceUnitStr, ivaStr, sign, bultosStr, "0"] + extraparams)
        return reply

    def subtotal(self, print_text=True, display=False, text="Subtotal"):
        if self._currentDocument in (self.CURRENT_DOC_TICKET, self.CURRENT_DOC_BILL_TICKET,
                self.CURRENT_DOC_CREDIT_TICKET):
            status = self._sendCommand(self.CMD_PRINT_SUBTOTAL[self._getCommandIndex()], ["P" if print_text else "O", text])
            return status
        raise NotImplementedError

    def dailyClose(self, type):
        reply = self._sendCommand(self.CMD_DAILY_CLOSE, [type, "P"])
        return reply[2:]

    def getLastNumber(self, letter):
        reply = self._sendCommand(self.CMD_STATUS_REQUEST, ["A"], True)
        if len(reply) < 3:
# La respuesta no es válida. Vuelvo a hacer el pedido y si hay algún error que se reporte como excepción
            reply = self._sendCommand(self.CMD_STATUS_REQUEST, ["A"], False)
        if letter == "A":
            return int(reply[6])
        else:
            return int(reply[4])

    def getLastCreditNoteNumber(self, letter):
        reply = self._sendCommand(self.CMD_STATUS_REQUEST, ["A"], True)
        if len(reply) < 3:
# La respuesta no es válida. Vuelvo a hacer el pedido y si hay algún error que se reporte como excepción
            reply = self._sendCommand(self.CMD_STATUS_REQUEST, ["A"], False)
        if letter == "A":
            return int(reply[10])
        else:
            return int(reply[11])

    def cancelAnyDocument(self):
        try:
            self._sendCommand(self.CMD_ADD_PAYMENT[0], ["Cancelar", "0", 'C'])
            return True
        except:
            pass
        try:
            self._sendCommand(self.CMD_ADD_PAYMENT[1], ["Cancelar", "0", 'C'])
            return True
        except:
            pass
        try:
            self._sendCommand(self.CMD_CLOSE_NON_FISCAL_RECEIPT, ["T"])
            return True
        except:
            pass
        return False

    def getWarnings(self):
        ret = []
        reply = self._sendCommand(self.CMD_STATUS_REQUEST, ["N"], True)
        printerStatus = reply[0]
        x = int(printerStatus, 16)
        if ((1 << 4) & x) == (1 << 4):
            ret.append("Poco papel para la cinta de auditoría")
        if ((1 << 5) & x) == (1 << 5):
            ret.append("Poco papel para comprobantes o tickets")
        return ret

    def __del__(self):
        try:
            self.close()
        except:
            pass

    def close(self):
        self.driver.close()
        self.driver = None
