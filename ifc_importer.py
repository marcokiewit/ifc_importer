# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ImportIFC
                                 A QGIS plugin
 Dieses Plugin importiert wesentliche Gebäudeattribute aus einer IFC Datei für den City Energy Analyst
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2022-01-17
        git sha              : $Format:%H$
        copyright            : (C) 2022 by Marco Kiewit
        email                : marco.kiewit@student.jade-hs.de
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.core import *
from qgis.gui import QgsMessageBar
from qgis.utils import iface
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

# --------------------
import osgeo.ogr as ogr
import osgeo.osr as osr
import sys, os
#sys.path.append(r'C:\Users\Marco\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\ifc_importer')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import ifcopenshell
from ifcopenshell import geom
from ifcopenshell.util import element
import dbf
import numpy as np

# --------------------

# Initialize Qt resources from file resources.py
from .resources import *
# Import the code for the dialog
from .ifc_importer_dialog import ImportIFCDialog
import os.path


class ImportIFC:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'ImportIFC_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&IFC Importer')

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('ImportIFC', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/ifc_importer/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'IFC Importer'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # will be set False in run()
        self.first_start = True


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&IFC Importer'),
                action)
            self.iface.removeToolBarIcon(action)
            
    def getTransformMatrix(self, project):
        def getModelContext(project):
            flag = False
            for context in project.RepresentationContexts:
                if context.ContextType == "Model":
                    flag = True
                    return context
            if flag == False:
                print ("No context for model was found in this project")

        contextForModel = getModelContext(project)
        a,b = contextForModel.TrueNorth.DirectionRatios
        transformMatrix = [[b, -a, 0], [a, b, 0], [0, 0, 1]]
        transformMatrix = np.mat(transformMatrix).I
        return transformMatrix
        
    def getOriginShift(self, site):
        def mergeDegrees(Degrees):
            if len(Degrees) == 4:
                degree = Degrees[0] + Degrees[1]/60.0 + (Degrees[2] + Degrees[3]/1000000.0)/3600.0
            elif len(Degrees) == 3:
                degree = Degrees[0]+Degrees[1]/60.0 + Degrees[2]/3600.0
            else:
                print("Wrong input of degrees")
            return degree
        Lat,Lon = site.RefLatitude, site.RefLongitude
        a, b = mergeDegrees(Lat), mergeDegrees(Lon)

        source = osr.SpatialReference()
        source.ImportFromEPSG(4326)
        # Berechnung des EPSG-Codes des Zielkoordinatensystems
        # Die WGS84-Grenzen für die UTM-Zone 32N (EPSG-Code 32632) liegen
        # zwischen 6° und 12°
        # Die WGS84-Grenzen für die UTM-Zone 33N (EPSG-Code 32633) liegen 
        # zwischen 12° und 18°
        if 18 > b >= 12:
            EPSG = 32633
        elif 6 <= b < 12:
            EPSG = 32632
        target = osr.SpatialReference()
        target.ImportFromEPSG(EPSG)
        transform = osr.CoordinateTransformation(source, target)
        x, y, z = transform.TransformPoint(a, b)
        c = site.RefElevation
        return [x, y, c]

    def georeferencingPoint(self, transMatrix, originShift, inX, inY):
        a = [inX, inY, 0]
        result = np.mat(a)*np.mat(transMatrix)+np.mat(originShift)
        return result
    
    def getBuildingFootprint(self, ifc_file, IfcBuilding, IfcSite, IfcProject):
        grouped_verts = []
        
        originShift = self.getOriginShift(IfcSite)
        trans = self.getTransformMatrix(IfcProject)

        if IfcBuilding.Representation != None:
            settings = geom.settings()
            # Gibt an, ob Subtypen von IfcCurve einbezogen werden sollen.
            settings.set(settings.INCLUDE_CURVES, True)
            settings.set(settings.USE_WORLD_COORDS, True)
            shape = geom.create_shape(settings, IfcBuilding)
            ios_vertices = shape.geometry.verts

            for i in range(0, len(ios_vertices), 3):
                result = self.georeferencingPoint(trans, originShift, ios_vertices[i], ios_vertices[i + 1])
                array = np.array(result)
                grouped_verts.append((array[0][0], array[0][1]))

        else:
            for ifc_entity in ifc_file.by_type("IfcBuildingElementProxyType"):
                try:
                    footprint = ifcopenshell.util.element.get_psets(ifc_entity)["Pset_BuildingElementProxyCommon"]["Reference"]
                    if footprint == "BuildingFootprint":
                        geometry = ifc_entity.RepresentationMaps[0].MappedRepresentation.Items[0]
                        t = geometry.SweptArea.OuterCurve.Points.CoordList
                except:
                    continue
                    
            for i in range(0, len(t) - 1):
                result = self.georeferencingPoint(trans, originShift, t[i][0], t[i][1])
                array = np.array(result)
                grouped_verts.append((array[0][0], array[0][1]))

        ring = ogr.Geometry(ogr.wkbLinearRing)
        for point in grouped_verts:
            ring.AddPoint(point[0], point[1])

        return ring
    
    def run(self):
        """Run method that performs all the real work"""

        # Create the dialog with elements (after translation) and keep reference
        # Only create GUI ONCE in callback, so that it will only load when the plugin is started
        if self.first_start == True:
            self.first_start = False
            self.dlg = ImportIFCDialog()

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:

            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            
            folder_path = self.dlg.localsave.filePath()
            save_path = self.dlg.localsave_2.filePath()
            ifc_file = ifcopenshell.open(folder_path)
            
            # Ausgabe der IFC-Version
            if ifc_file.schema != "IFC4":
                print("Falsche IFC-Version. Nur IFC4 erlaubt!")
                sys.exit(0)
            
            #########################
            
            IfcProject = ifc_file.by_type("IfcProject")[0]
            IfcSite = ifc_file.by_type("IfcSite")[0]
            IfcBuilding = ifc_file.by_type("IfcBuilding")[0]

            buildingFootprint = self.getBuildingFootprint(ifc_file, IfcBuilding, IfcSite, IfcProject)
            print(buildingFootprint)
                            
            ################################
            # Extrahierung des Baujahrs, Konstruktionstyps, Gebäudenamen

            Year_of_construction = ifcopenshell.util.element.get_psets(IfcBuilding)["Pset_BuildingCommon"]["YearOfConstruction"]
            OccupancyType = ifcopenshell.util.element.get_psets(IfcBuilding)["Pset_BuildingCommon"]["OccupancyType"]
            BuildingName = IfcBuilding.LongName
            
            print("Year_of_construction: ", Year_of_construction)
            print("OccupancyType: ", OccupancyType)
            #print(BuildingHeight)
            print("BuildingName: ", BuildingName)
            Year_of_construction = int(Year_of_construction)
            
            # Berechnung des Standards
            BuildingStandard =""
            
            if 1000 < Year_of_construction <= 1920:
                BuildingStandard = "STANDARD1"
            elif 1921 <= Year_of_construction <= 1970:
                BuildingStandard = "STANDARD2"
            elif 1971 <= Year_of_construction <= 1980:
                BuildingStandard = "STANDARD3"
            elif 1981 <= Year_of_construction <= 2000:
                BuildingStandard = "STANDARD4"
            elif 2001 <= Year_of_construction <= 2040:
                BuildingStandard = "STANDARD5"
            else:
                BuildingStandard = "k. A."

            print("BuildingStandard: ", BuildingStandard)

            ######################
            
            # Rauminformationen extrahieren
            
            try:
                gesamtFlaeche = 0

                IfcSpace = ifc_file.by_type("IfcSpace")[0]
                for ifc_entity in ifc_file.by_type("IfcSpace"):
                    nutzung_in_m2 = ifcopenshell.util.element.get_psets(ifc_entity)["BaseQuantities"]["NetFloorArea"]
                    #nutzung_in_m2 = ifcopenshell.util.element.get_psets(ifc_entity)["BaseQuantities"]["Gemessene Nettofläche"]
                    gesamtFlaeche += nutzung_in_m2

                for ifc_entity in ifc_file.by_type("IfcSpace"):

                    raumName = ifc_entity.LongName
                    nutzung_in_m2 = ifcopenshell.util.element.get_psets(ifc_entity)["BaseQuantities"]["NetFloorArea"]
                    print(raumName, nutzung_in_m2 , " m2,", " Nutzungsverteilung im Gebäude: ", (nutzung_in_m2/gesamtFlaeche)*100)

            except:
                print("Keine Raunminformationen vorhanden!")
                
            
            ################################

            building_height = 0
            floors_ag = 0
            floors_bg = 0
            height_ag = 0
            height_bg = 0

            # Extrahierung des Typ der Konstruktion
            for ifc_entity in ifc_file.by_type("IfcBuildingStorey"):
                above = ifcopenshell.util.element.get_psets(ifc_entity)["Pset_BuildingStoreyCommon"]["AboveGround"]
                storey_height = ifcopenshell.util.element.get_psets(ifc_entity)["Qto_BuildingStoreyBaseQuantities"]["GrossHeight"]
                #storey_height = ifcopenshell.util.element.get_psets(ifc_entity)["BaseQuantities"]["GrossHeight"]
                if above == True:
                    floors_ag += 1
                    height_ag += storey_height
                elif above == False:
                    floors_bg += 1
                    height_bg += storey_height
                building_height += storey_height
            
            # Runden der Höhen
            height_ag = int(round(height_ag,0))
            height_bg = int(round(height_bg,0))
            
            print("floors_ag: ", floors_ag)
            print("floors_bg: ", floors_bg)
            print("height_ag: ", height_ag)
            print("height_bg: ", height_bg)

            building_height = int(round(building_height,0))

            ################################
            
            driver = ogr.GetDriverByName("ESRI Shapefile")
            try:
                data_source = driver.CreateDataSource(save_path + "\\zone.shp")

                # Berechnung des EPSG-Codes des Zielkoordinatensystems
                # Die WGS84-Grenzen für die UTM-Zone 32N (EPSG-Code 32632) liegen
                # zwischen 6° und 12°
                # Die WGS84-Grenzen für die UTM-Zone 33N (EPSG-Code 32633) liegen 
                # zwischen 12° und 18°

                lon = IfcSite.RefLongitude[0]
                if 18 > lon >= 12:
                    EPSG = 32633
                elif 6 <= lon < 12:
                    EPSG = 32632
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(EPSG)

                # create the layer
                layer = data_source.CreateLayer("IfcBuilding", srs, ogr.wkbPolygon)
                
                # Add the fields we're interested in
                field_name1 = ogr.FieldDefn("Name", ogr.OFTString)
                field_name2 = ogr.FieldDefn("floors_ag", ogr.OFTInteger)
                field_name3 = ogr.FieldDefn("floors_bg", ogr.OFTInteger)
                field_name4 = ogr.FieldDefn("height_ag", ogr.OFTInteger)
                field_name5 = ogr.FieldDefn("height_bg", ogr.OFTInteger)
                field_name1.SetWidth(80)
                field_name2.SetWidth(10)
                field_name3.SetWidth(10)
                field_name4.SetWidth(10)
                field_name5.SetWidth(10)
                
                layer.CreateField(field_name1)
                layer.CreateField(field_name2)
                layer.CreateField(field_name3)
                layer.CreateField(field_name4)
                layer.CreateField(field_name5)
            except:
                print("Die Aktion kann nicht abgeschlossen werden, da die Datei noch geöffnet ist.")
 
            
            ################################
            
            try:
                poly = ogr.Geometry(ogr.wkbPolygon)
                poly.AddGeometry(buildingFootprint)

                feature = ogr.Feature(layer.GetLayerDefn())

                # Set the feature geometry using the point
                feature.SetGeometry(poly)
                feature.SetField('Name', BuildingName)
                feature.SetField('floors_ag', floors_ag)
                feature.SetField('floors_bg', floors_bg)
                feature.SetField('height_ag', height_ag)
                feature.SetField('height_bg', height_bg)

                # Create the feature in the layer (shapefile)
                layer.CreateFeature(feature)
                # Dereference the feature
                feature = None

                # Save and close the data source
                data_source = None
                
                # Layer dem QGIS-Projekt hinzufügen
                project = QgsProject.instance()
            
                vlayer = QgsVectorLayer(save_path +"\\zone.shp","zone",'ogr')
                vlayer.setCrs(QgsCoordinateReferenceSystem(EPSG))
                QgsProject.instance().addMapLayer(vlayer)
            except:
                iface.messageBar().pushMessage("Error","Die Aktion kann nicht abgeschlossen werden, da die Datei noch geöffnet ist.", level=Qgis.Critical)
            
            # Typology-Datei erzeugen
            try:
                spalten =   ("NAME C(25)", 
                            "STANDARD C(25)",
                            "YEAR N(20,0)",
                            "1ST_USE C(25)",
                            "1ST_USE_R N(20,0)",
                            "2ND_USE C(25)",
                            "2ND_USE_R N(20,0)",
                            "3RD_USE C(25)",
                            "3RD_USE_R N(20,0)",
                            "REFERENCE N(36,15)"
                            )

                table = dbf.Table(
                    filename=save_path + "\\typology.dbf",
                    field_specs=spalten,
                    on_disk=True
                    )
                
                table.open(dbf.READ_WRITE)
                table.append((BuildingName, 
                            BuildingStandard, 
                            Year_of_construction,
                            OccupancyType,
                            1,
                            "NONE",
                            0,
                            "NONE",
                            0))

                for record in table:
                    print(record)
                    
                table.close()
            except:
                iface.messageBar().pushMessage("Error","Die Erzeugung der typology.dbf hat nicht geklappt!", level=Qgis.Critical)

