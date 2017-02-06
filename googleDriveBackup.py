from __future__ import print_function
import httplib2
import os
import datetime
import hashlib

from time import sleep
from googleapiclient.http import MediaFileUpload
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage

try:
	import argparse
	flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
	flags = None

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/drive-python-quickstart.json
SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Drive API Python Quickstart'
BKP_FOLDER_ID = '0B0dn6haaox2Vak9aNktqZmtLWTg'
BKP_LOCAL_DIR = 'D:\Projects\Python\Drive API\Test'

def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_credentials():
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

def convertToRFC3399(s):
	return datetime.datetime.fromtimestamp(s).strftime('%Y-%m-%dT%H:%M:%S+05:30');

def main():
	"""Shows basic usage of the Google Drive API.

	Creates a Google Drive API service object and outputs the names and IDs
	for up to 10 files.
	"""
	credentials = get_credentials()
	http = credentials.authorize(httplib2.Http())
	service = discovery.build('drive', 'v3', http=http)

	folderId = {BKP_LOCAL_DIR:BKP_FOLDER_ID}

	# traverse root directory, and list directories as dirs and files as files
	for root, dirs, files in os.walk(BKP_LOCAL_DIR):
		print(root)
		path = root.split(os.sep)
		folderName = os.path.basename(root)
		currentFolderId = folderId.get(root,None)
		
		# fetch/assign id for all sub directories
		for directory in dirs:
			dirPath = root+"\\"+directory;
			#check if the folder exist otherwise create it
			results = service.files().list(pageSize=10,fields="files(id, name)",q="'"+currentFolderId+"' in parents and name = '"+directory+"' and mimeType = 'application/vnd.google-apps.folder' and trashed = false").execute()
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

		# upload the files in the folder
		print((len(path) - 1) * '---', os.path.basename(root))
		for filename in files:
			print(len(path) * '---', filename)
			#check if file exists
			results = service.files().list(pageSize=1,fields="files(id, name)",q="'"+currentFolderId+"' in parents and name = '"+filename+"' and mimeType != 'application/vnd.google-apps.folder' and trashed = false").execute()
			items = results.get('files', []);
			if not items:
				#TODO escape file check
				filePath = root+"\\"+filename
				file_metadata = {
				'name' : filename,
				'parents': [ currentFolderId ],
				'createdTime' : convertToRFC3399(os.path.getctime(filePath)),
				'modifiedTime' : convertToRFC3399(os.path.getmtime(filePath))
				}
				
				media = MediaFileUpload(filePath, resumable=True)
				fileUploaded = service.files().create(body=file_metadata, media_body=media, fields='id,md5Checksum').execute()
				if fileUploaded["md5Checksum"] == md5(filePath):
					print("File Uploaded Successfully")
				else:
					print("File's corrupted")
			else:
				print("Already Exists!")
			

	results = service.files().list(
		pageSize=20,fields="nextPageToken, files(id, name, md5Checksum, parents)",q="'"+BKP_FOLDER_ID+"' in parents and trashed = false").execute()
	items = results.get('files', [])
	print(results)
	if not items:
		print('No files found.')
	else:
		print('Files:')
		for item in items:
			print('{0} ({1})'.format(item['name'], item['id']))

if __name__ == '__main__':
	main()
