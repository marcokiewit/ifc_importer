import os
import sys
sys.path.append(r'C:\Users\Marco\OneDrive\Masterarbeit\Dateien\QGIS_Plugin\ifc_importer')
import ifcopenshell.util.element
def getPropertyDefinition(file, property):
    return ifcopenshell.util.element.get_property_definition(file.by_type(property)[0])