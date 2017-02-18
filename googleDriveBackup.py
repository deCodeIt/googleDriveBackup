from __future__ import print_function
import httplib2
import os
import datetime
import hashlib

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
	parser.add_argument("-d","--directory",help="The directory path to backup");
	flags = parser.parse_args()
except ImportError:
	pass

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/drive-python-quickstart.json
SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Drive API Python Quickstart'
BKP_FOLDER_ID = '0B0dn6haaox2Vak9aNktqZmtLWTg'
BKP_LOCAL_DIR = 'D:\Projects\Python\Drive API\BKP\Test'
NUM_FILES_PER_REQUEST = 1

def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_credentials():
	global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID
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

def doUpload(service, file_metadata, media, filePath):
	global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID
	filename = file_metadata.get("name")
	fileUploaded = service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')

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
				fileUploaded = service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')
			
		except HttpError as e:
			print (e.resp.status)
			if e.resp.status in [ 402, 404]:
			# Start the upload all over again.
				fileUploaded = service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum')
			elif e.resp.status in [500, 502, 503, 504, 408]:
				continue
			# Call next_chunk() again, but use an exponential backoff for repeated errors.
			else:
			# Do not retry. Log the error and fail.
				print("An unknown error has occurred, Failed to upload: {0}".format(filename))
				flag = True
		except ConnectionResetError as cre:
			print ("Connection has been reset, Resuming Upload", end="\r")

def convertToRFC3399(s):
	return datetime.datetime.fromtimestamp(s).strftime('%Y-%m-%dT%H:%M:%S+05:30');

def main():
	global SCOPES, CLIENT_SECRET_FILE, APPLICATION_NAME, BKP_LOCAL_DIR, BKP_FOLDER_ID, NUM_FILES_PER_REQUEST
	"""Shows basic usage of the Google Drive API.

	Creates a Google Drive API service object and outputs the names and IDs
	for up to 10 files.
	"""
	# backup the supplied directory
	if flags and flags.directory:
		BKP_LOCAL_DIR = flags.directory

	credentials = get_credentials()
	http = credentials.authorize(httplib2.Http())
	service = discovery.build('drive', 'v3', http=http)

	folderId = {BKP_LOCAL_DIR:BKP_FOLDER_ID}

	# traverse root directory, and list directories as dirs and files as files
	for root, dirs, files in os.walk(BKP_LOCAL_DIR):
		path = root.split(os.sep)
		folderName = os.path.basename(root)
		currentFolderId = folderId.get(root,None)
		
		# fetch/assign id for all sub directories
		for directory in dirs:
			dirPath = root+os.path.sep+directory;
			#check if the folder exist otherwise create it
			results = service.files().list(pageSize=1,fields="files(id, name)",q="'"+currentFolderId+"' in parents and name = '"+directory+"' and mimeType = 'application/vnd.google-apps.folder' and trashed = false").execute()
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
				createdfolder =service.files().create(body=file_metadata, fields='id').execute()
				folderId[dirPath] = createdfolder['id']
			else:
				# the folder is present on cloud so store its id
				folderId[dirPath] = items[0]['id']
		# get the list of files in this folder on cloud
		filesOnCloud = []
		pageToken = None
		while True:
			results = service.files().list(pageSize=NUM_FILES_PER_REQUEST,pageToken = pageToken,fields="files(id, name,md5Checksum), nextPageToken",q="'"+currentFolderId+"' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false").execute()
			fileItems = results.get('files',[])
			if not fileItems:
				break;
			else:
				# get files from array to our local array
				filesOnCloud.extend(fileItems);
				if not results.get('nextPageToken',False):
					break;
				else:
					pageToken = results.get('nextPageToken')

		print(filesOnCloud);

		# upload the files in the folder
		print((len(path) - 1) * '---', os.path.basename(root))
		for filename in files:
			filePath = root+os.path.sep+filename
			filenameDrive = filename.replace("'","\\'") # for single quote error in searching drive for file name
			print(len(path) * '---', filename)
			#check if file exists
			results = service.files().list(pageSize=1,fields="files(id, name,md5Checksum)",q="'"+currentFolderId+"' in parents and name = '"+filenameDrive+"' and mimeType != 'application/vnd.google-apps.folder' and trashed = false").execute()
			items = results.get('files', []);
			if not items or items[0]["md5Checksum"] != md5(filePath):
				#TODO escape file check
				file_metadata = {
				'name' : filename,
				'parents': [ currentFolderId ],
				'createdTime' : convertToRFC3399(os.path.getctime(filePath)),
				'modifiedTime' : convertToRFC3399(os.path.getmtime(filePath))
				}
				
				media = MediaFileUpload(filePath, chunksize=1048576, resumable=True)
				
				doUpload(service,file_metadata,media, filePath)
				
				
			else:
				print("Already Exists!")
			

	# results = service.files().list(
	# 	pageSize=20,fields="nextPageToken, files(id, name, md5Checksum, parents)",q="'"+BKP_FOLDER_ID+"' in parents and trashed = false").execute()
	# items = results.get('files', [])
	# print(results)
	# if not items:
	# 	print('No files found.')
	# else:
	# 	print('Files:')
	# 	for item in items:
	# 		print('{0} ({1})'.format(item['name'], item['id']))

if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt as e:
		print ("Terminated By User")
	else:
		print("Unknown Error has Occurred -_-? ")
		
	
