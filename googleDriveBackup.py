from __future__ import print_function
import httplib2
import os, sys
import datetime
import hashlib
import pdb

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from time import sleep
from googleapiclient.http import MediaFileUpload
from apiclient.errors import HttpError
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
flags = None
try:
	import argparse
	parser = argparse.ArgumentParser(parents=[tools.argparser])
	# parser.add_argument("-d","--directory",help="The directory path to backup");
	flags = parser.parse_args()
except ImportError:
	pass

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/drive-python-quickstart.json
SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Drive API Python Quickstart'
# BKP_FOLDER_ID = '0B0dn6haaox2Vak9aNktqZmtLWTg'
BKP_FOLDER_ID = 'root'
BKP_LOCAL_DIR = None
NUM_FILES_PER_REQUEST = 100
DB = None # stores the DriveBackup object

class MyQLabel(QLabel):
	# for truncated Label Names (directory names)
    def paintEvent( self, event ):
        painter = QPainter(self)

        metrics = QFontMetrics(self.font())
        elided  = metrics.elidedText(self.text(), Qt.ElideRight, self.width())

        painter.drawText(self.rect(), self.alignment(), elided)

class QDoublePushButton(QPushButton):
    doubleClicked = pyqtSignal()
    clicked = pyqtSignal()
    selected = pyqtSignal()

    def __init__(self, *args, **kwargs):
        QPushButton.__init__(self, *args, **kwargs)
        self.setSizePolicy ( QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        super().clicked.connect(self.selected.emit)
        self.timer.timeout.connect(self.clicked.emit)
        super().clicked.connect(self.checkDoubleClick)

    @pyqtSlot()
    def checkDoubleClick(self):
        if self.timer.isActive():
            self.doubleClicked.emit()
            self.timer.stop()
        else:
            self.timer.start(250)


class driveFoldersThread(QThread):
	foldersLoaded = pyqtSignal(object)

	def __init__(self,folderId):
		QThread.__init__(self)
		self.folderId = folderId
		global DB,app
		self.DB = DB
		self.app = app

	def __del__(self):
		self.wait()

	def getFolderDetails(self,currentFolderId='root'):
		# returns object array [{'name':'....', 'id':'...'}, ...]
		# get the list of files in this folder on cloud
		folderOnCloud = []
		pageToken = None
		while True:
			results = self.DB.service.files().list(pageSize=NUM_FILES_PER_REQUEST,pageToken = pageToken,fields="files(id, name), nextPageToken",q="'"+currentFolderId+"' in parents and 'me' in owners and mimeType = 'application/vnd.google-apps.folder' and trashed = false").execute()
			folderItems = results.get('files',[])
			if not folderItems:
				break;
			else:
				# get files from array to our local dictionary
				folderOnCloud.extend(folderItems);
				if not results.get('nextPageToken',False):
					break;
				else:
					pageToken = results.get('nextPageToken')
		return folderOnCloud

	def run(self):
		folders = self.getFolderDetails(self.folderId)
		self.foldersLoaded.emit(folders) # signal that the folder list has been fetched from cloud

class Folder(QWidget):
	'''Displays the folder content as folder icon and folder label'''
	
	folderSelected = pyqtSignal(object)
	folderOpen = pyqtSignal(object)

	def __init__(self,folder):
		QWidget.__init__(self)
		self.folder = folder
		self.initUI()

	def initUI(self):
		self.b = QDoublePushButton('')
		self.b.setFixedSize(48,48)
		self.b.setFlat(True)
		self.b.setIcon(QIcon('icons/folder_blue.png'))
		self.b.setIconSize(QSize(48,48))
		self.b.setToolTip(self.folder["name"])
		
		self.b.doubleClicked.connect(lambda _folder=self.folder : self.folderOpen.emit(_folder))

		self.dirName = MyQLabel()
		self.dirName.setText(self.folder["name"])
		# self.dirName.setReadOnly(True)
		self.dirName.setWordWrap(True)
		self.dirName.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
		self.dirName.setFixedWidth(48)
		self.dirName.setFixedHeight(16)
		# dirName.setStyleSheet("background-color:yellow;")
		self.dirName.setAlignment(Qt.AlignHCenter)

		# highlight this folder label when selected
		self.b.selected.connect(self.selectFolder)

		folderContainer = QVBoxLayout()
		folderContainer.addWidget(self.b)
		folderContainer.addWidget(self.dirName)
		# folderContainerWidget = QWidget()
		# folderContainerWidget.setLayout(folderContainer)
		self.setLayout(folderContainer)
		# folderContainerWidget.setStyleSheet("background-color:yellow;")

	@pyqtSlot()
	def selectFolder(self):
		# b.setStyleSheet('background-color:#FFFF00;')
		self.highlightFolder()
		self.folderSelected.emit( self.folder ) # signals which folder is clicked

	def highlightFolder(self,select=True):
		if select:
			self.dirName.setStyleSheet('background-color:#FFFF00;')
		else:
			self.dirName.setStyleSheet('background-color:#FFFFFF;')


class DirectoryViewer(QScrollArea):
	'''
		shows the directories in the GUI as scrollArea
	'''
	def __init__(self):
		global DB, app
		QScrollArea.__init__(self)
		self.MAX_FOLDERS_IN_A_ROW = 7
		self.remoteBackupFolderId = 'root' # by default upload to root/home directory
		self.DB = DB
		self.app = app
		self.setStyleSheet('background-color:#FFF;')
		self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.setWidgetResizable(False)
		self.loadingMovie = QMovie('icons/loading.gif')
		
		# self.initializeLoadingWidget()
		
		# #create a gridlayout for destination Cloud folder selection
		self.driveLayout = QGridLayout()
		self.driveLayout.setHorizontalSpacing(20)

		# # #set the layout in a widget
		self.qDriveWidget = QWidget()
		self.qDriveWidget.setLayout(self.driveLayout)

		self.open_folder('root')

	def safelyClearDriveLayout(self):
		'''Remove the  previously loaded contents on GUI from memory'''
		if not self.driveLayout:
			pass;
		else:
			for i in reversed(range(self.driveLayout.count())): 
				widgetToRemove = self.driveLayout.itemAt( i ).widget()
				# remove it from the layout list
				self.driveLayout.removeWidget( widgetToRemove )
				# remove it from the gui
				# widgetToRemove.hide()
				widgetToRemove.deleteLater()
				widgetToRemove.setParent(None)
	
	def getLoadingWidget(self):
		'''The loading icon shown while fetching directories from server'''
		_loadingImageContainer = QLabel()
		_loadingImageContainer.setMovie(self.loadingMovie)
		self.loadingMovie.start()

		_loadingLabel = QLabel()
		_loadingLabel.setText("Loading...")
		_loadingLabel.setAlignment(Qt.AlignHCenter)

		_loadingLayout = QVBoxLayout()
		_loadingLayout.addWidget(_loadingImageContainer)
		_loadingLayout.addWidget(_loadingLabel)

		_loadingLayoutWidget = QWidget()
		_loadingLayoutWidget.setLayout(_loadingLayout)

		return _loadingLayoutWidget

	def startLoading(self):
		'''Display the Loading GUI'''
		# self.loadingLayoutWidget.setStyleSheet('background-color:#FFF;')
		self.setWidget(self.getLoadingWidget())
		self.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

	@pyqtSlot(object)
	def stopLoading(self,folders=[]):
		'''Stop the loading GUI and display fetched directories'''
		self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
		self._open_folder(folders)
	
	@pyqtSlot()
	def open_folder(self,folderId='root'):
		'''fetch the directory contents(directories only) of the selected directory'''
		self.remoteBackupFolderId = folderId # sets the folder to be backed up
		self.startLoading()
		self.thread = driveFoldersThread(folderId)
		self.thread.foldersLoaded.connect(self.stopLoading)
		self.thread.start()

	@pyqtSlot()
	def _open_folder(self,folders):
		'''Display the fetched folders from folder list in GUI'''
		self.driveLayout = QGridLayout()
		self.driveLayout.setHorizontalSpacing(20)
		self.qDriveWidget = QWidget()
		self.qDriveWidget.setLayout(self.driveLayout)

		if not folders:
			#write Empty
			notifyText = QLabel()
			notifyText.setText("Folder is Empty")
			notifyText.setAlignment(Qt.AlignHCenter)

			self.driveLayout.addWidget(notifyText,1,1)

		#create the folder layout
		r = 0
		c = 0
		for folder in folders:
			
			folderContainerWidget = Folder(folder);
			folderContainerWidget.folderSelected.connect(self.select_folder)
			folderContainerWidget.folderOpen.connect(self.view_folder)
			self.driveLayout.addWidget(folderContainerWidget,r,c)

			# change the row and column for next folder
			c+=1
			if(c>=self.MAX_FOLDERS_IN_A_ROW):
				c=0
				r+=1
		#set the layout of directory Container to Directory grid layout
		self.setWidget(self.qDriveWidget)

	@pyqtSlot(object)
	def view_folder(self,folder=None):
		''' process and then open the selected folder'''

		self.open_folder(folder["id"])

	@pyqtSlot(object)
	def select_folder(self,folder=None):
		# pdb.set_trace()
		self.remoteBackupFolderId = folder["id"] # sets the folder to be backed up
		for i in range(self.driveLayout.count()):
			fcw = self.driveLayout.itemAt(i).widget() # gets the widget
			if fcw.folder["name"] == folder["name"]:
				fcw.highlightFolder(True) # highlight the selected folder
			else:
				fcw.highlightFolder(False) # removes highlight from other folders



class App(QWidget):
	global BKP_FOLDER_ID,DB
	def __init__(self):
		super().__init__()
		self.title = 'Google Drive Smart BackUp'
		self.left = 200
		self.top = 200
		self.width = 640
		self.height = 480
		self.scrollDirectoryContainer = None
		self.DB = DB
		self.initUI()

	def initUI(self):
		self.setWindowTitle(self.title)
		self.setGeometry(self.left, self.top, self.width, self.height)
		self.setFixedSize(self.width,self.height)
		
		# page for upload folder selection
		backupFolderPage = self.createGridLayoutForBackupFolderSelection()
		
		# to hold this layout in a widget and pass it to stackedLayout
		qwidget = QWidget()
		qwidget.setLayout(backupFolderPage)

		#stacked layout for combining pages(layouts/widgets)
		self.stackedLayout = QStackedLayout()
		self.stackedLayout.addWidget(qwidget)
		self.setLayout(self.stackedLayout)

		# set currrent Layout
		self.stackedLayout.setCurrentIndex(0)


		# self.statusBar().showMessage('Message in statusbar.')
		self.show()

	def createGridLayoutForBackupFolderSelection(self):
		"""
		As the name suggests, it creates the layout for
		"""
		horizontalGroupBox = QGroupBox("BackUp Folder Selection")
		horizontalGroupBox.setAlignment(Qt.AlignHCenter)
		layout = QGridLayout()
		layout.setRowStretch(0, 1)
		layout.setRowStretch(2, 8)
		layout.setColumnStretch(0, 9)
		layout.setColumnStretch(1, 1)
		
		#hint for Qline/path of directory selected
		self.textForFolderSelection = QLineEdit(self)
		self.textForFolderSelection.setReadOnly(True)
		self.textForFolderSelection.setPlaceholderText('Select a Folder to BackUp')

		# button for folder selection
		self.buttonForFolderSelection = QPushButton('Select', self)
		self.buttonForFolderSelection.setToolTip('Choose folder to backUp')
		self.buttonForFolderSelection.clicked.connect(self.openFolderDialog)

		#create a scrollArea for directories to be visible
		self.scrollDirectoryContainer = DirectoryViewer()

		# add the widgets accordingly
		layout.addWidget(self.textForFolderSelection,1,0) 
		layout.addWidget(self.buttonForFolderSelection,1,1)
		layout.addWidget(self.scrollDirectoryContainer,2,0,1,2)

		horizontalGroupBox.setLayout(layout)

		# button at bottom to initiate backup
		uploadButtonContainer = QHBoxLayout()

		buttonForUpload = QPushButton('BackUp Now', self)
		buttonForUpload.setToolTip('Initiate BackUp')
		buttonForUpload.clicked.connect(self.do_upload)

		# for Right Alignment
		uploadButtonContainer.addStretch(8)
		uploadButtonContainer.addWidget(buttonForUpload)

		windowLayout = QVBoxLayout()
		windowLayout.addWidget(horizontalGroupBox)
		windowLayout.addLayout(uploadButtonContainer)

		return windowLayout

	@pyqtSlot()
	def openFolderDialog(self):
		"""
		Asks user to choose the Local folder that needs to be backed up on drive
		"""
		global BKP_LOCAL_DIR
		options = QFileDialog.Options()
		# options |= QFileDialog.DontUseNativeDialog
		options |= QFileDialog.ShowDirsOnly
		folderPath = QFileDialog.getExistingDirectory(self,"Folder to BackUp", "", options=options)
		if folderPath:
			BKP_LOCAL_DIR = folderPath
			self.textForFolderSelection.setText(BKP_LOCAL_DIR)


	def do_upload(self):
		global BKP_FOLDER_ID
		BKP_FOLDER_ID = self.scrollDirectoryContainer.remoteBackupFolderId
		self.DB.mainUpload()

class DriveBackup():

	def __init__(self):
		# global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID, NUM_FILES_PER_REQUEST
		
		self.credentials = self.get_credentials()
		self.http = self.credentials.authorize(httplib2.Http())
		self.service = discovery.build('drive', 'v3', http=self.http)

	def get_credentials(self):
		global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME
		"""Gets valid user credentials from storage.

		If nothing has been stored, or if the stored credentials are invalid,
		the OAuth2 flow is completed to obtain the new credentials.

		Returns:
			Credentials, the obtained credential.
		"""
		home_dir = os.path.expanduser('~')
		credential_dir = os.path.join(home_dir, '.credentials')
		if not os.path.exists(credential_dir):
			os.makedirs(credential_dir)
		credential_path = os.path.join(credential_dir,
									   'drive-python-quickstart.json')

		store = Storage(credential_path)
		credentials = store.get()
		if not credentials or credentials.invalid:
			flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
			flow.user_agent = APPLICATION_NAME
			if flags:
				credentials = tools.run_flow(flow, store, flags)
			else: # Needed only for compatibility with Python 2.6
				credentials = tools.run(flow, store)
			print('Storing credentials to ' + credential_path)
		return credentials

	def doUpload(self, file_metadata, media, filePath):
		global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID
		filename = file_metadata.get("name")
		fileUploaded = self.service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')

		response = None
		flag = False
		while not flag:
			try:
				while response is None:
					status, response = fileUploaded.next_chunk()
					if status:
						print ("Uploaded {0:.2f}%.".format(status.progress() * 100),end="\r")
				# file Upload successful, corruption would be checked for later
				#Check MD5 checksum later
				if response["md5Checksum"] == md5(filePath):
					print("File Uploaded Successfully")
					flag = True # end the file upload
				else:
					print("File's corrupted on Drive, Uploading Again :(", end="\r")
					fileUploaded = self.service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')
				
			except HttpError as e:
				print (e.resp.status)
				if e.resp.status in [ 402, 404]:
				# Start the upload all over again.
					fileUploaded = self.service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')
				elif e.resp.status in [500, 502, 503, 504, 408]:
					continue
				# Call next_chunk() again, but use an exponential backoff for repeated errors.
				else:
				# Do not retry. Log the error and fail.
					print("An unknown error has occurred, Failed to upload: {0}".format(filename))
					flag = True
			except ConnectionResetError as cre:
				print ("Connection has been reset, Resuming Upload", end="\r")


	def mainUpload(self):
		global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID, NUM_FILES_PER_REQUEST
		"""Shows basic usage of the Google Drive API.

		Creates a Google Drive API service object and outputs the names and IDs
		for up to 10 files.
		"""
		# backup the supplied directory
		# if flags and flags.directory:
		# 	BKP_LOCAL_DIR = flags.directory

		folderId = {BKP_LOCAL_DIR:BKP_FOLDER_ID}
		print(folderId)

		# traverse root directory, and list directories as dirs and files as files
		for root, dirs, files in os.walk(BKP_LOCAL_DIR):
			path = root.split(os.sep)
			folderName = os.path.basename(root)
			# currentFolderId = folderId.get(root,None)
			currentFolderId = folderId.get(root,'root')
			
			# fetch/assign id for all sub directories
			for directory in dirs:
				dirPath = root+os.path.sep+directory;
				#check if the folder exist otherwise create it
				results = self.service.files().list(pageSize=1,fields="files(id, name)",q="'"+currentFolderId+"' in parents and name = '"+directory+"' and mimeType = 'application/vnd.google-apps.folder' and trashed = false").execute()
				items = results.get('files', [])
				if not items:
					# create the folder and store its id
					file_metadata = {
					'name' : directory,
					'mimeType' : 'application/vnd.google-apps.folder',
					'parents' : [currentFolderId],
					'createdTime' : convertToRFC3399(os.path.getctime(dirPath)),
					'modifiedTime' : convertToRFC3399(os.path.getmtime(dirPath))
					}
					createdfolder = self.service.files().create(body=file_metadata, fields='id').execute()
					folderId[dirPath] = createdfolder['id']
				else:
					# the folder is present on cloud so store its id
					folderId[dirPath] = items[0]['id']
			# get the list of files in this folder on cloud
			filesOnCloud = {}
			pageToken = None
			while True:
				results = self.service.files().list(pageSize=NUM_FILES_PER_REQUEST,pageToken = pageToken,fields="files(id, name,md5Checksum), nextPageToken",q="'"+currentFolderId+"' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false").execute()
				fileItems = results.get('files',[])
				if not fileItems:
					break;
				else:
					# get files from array to our local dictionary
					# filesOnCloud.extend(fileItems);
					for fileC in fileItems:
						nameOfFile = fileC.get('name')
						md5OfFile = fileC.get('md5Checksum')
						# idOfFile = fileC.get('id')
						filesOnCloud[nameOfFile] = {'md5Checksum':md5OfFile} # NAME SHOULD BE UNIQUE IN A GIVEN FOLDER

					if not results.get('nextPageToken',False):
						break;
					else:
						pageToken = results.get('nextPageToken')

			# print(filesOnCloud);

			# upload the files in the folder
			print((len(path) - 1) * '---', os.path.basename(root))
			for filename in files:
				filePath = root+os.path.sep+filename
				filenameDrive = filename.replace("'","\\'") # for single quote error in searching drive for file name
				print(len(path) * '---', filename)
				#check if file exists
				fileDetail = filesOnCloud.get(filename,None);
				if fileDetail!=None and md5(filePath) == fileDetail["md5Checksum"]:
					print("Already Exists on Drive!")
					continue; # file is already present on cloud
				else:
					file_metadata = {
					'name' : filename,
					'parents': [ currentFolderId ],
					'createdTime' : convertToRFC3399(os.path.getctime(filePath)),
					'modifiedTime' : convertToRFC3399(os.path.getmtime(filePath))
					}
					media = MediaFileUpload(filePath, chunksize=1048576, resumable=True)
					self.doUpload(file_metadata,media, filePath)
				

		# results = self.service.files().list(
		# 	pageSize=20,fields="nextPageToken, files(id, name, md5Checksum, parents)",q="'"+BKP_FOLDER_ID+"' in parents and trashed = false").execute()
		# items = results.get('files', [])
		# print(results)
		# if not items:
		# 	print('No files found.')
		# else:
		# 	print('Files:')
		# 	for item in items:
		# 		print('{0} ({1})'.format(item['name'], item['id']))

def md5(fname):
	hash_md5 = hashlib.md5()
	with open(fname, "rb") as f:
		for chunk in iter(lambda: f.read(4096), b""):
			hash_md5.update(chunk)
	return hash_md5.hexdigest()

def convertToRFC3399(s):
	return datetime.datetime.fromtimestamp(s).strftime('%Y-%m-%dT%H:%M:%S+05:30');

if __name__ == '__main__':
	try:
		DB = DriveBackup()
		app = QApplication(sys.argv)
		ex = App()
		sys.exit(app.exec_())
	except KeyboardInterrupt as e:
		print ("Terminated By User")
	
		
	
