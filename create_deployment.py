import os
import zipfile
from datetime import datetime

def create_deployment_zip():
    # Get current timestamp for the zip filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_filename = f'deployment_{timestamp}.zip'
    
    # Files and directories to include
    include_patterns = [
        'application.py',
        'models.py',
        'email_utils.py',
        'requirements.txt',
        'Procfile',
        'runtime.txt',
        '.ebextensions',
        'templates',
        'static'
    ]
    
    # Files and directories to exclude
    exclude_patterns = [
        '__pycache__',
        '.git',
        '.env',
        'venv',
        'ENV',
        '.idea',
        '.vscode',
        '*.pyc',
        '*.pyo',
        '*.pyd',
        '.Python',
        '*.so',
        '*.egg',
        '*.egg-info',
        'dist',
        'build',
        '*.log',
        'create_deployment.py'  # Exclude this script itself
    ]
    
    print(f"Creating deployment package: {zip_filename}")
    print("\nChecking required files:")
    
    # Check if all required files exist
    missing_files = []
    for pattern in include_patterns:
        if not os.path.exists(pattern):
            missing_files.append(pattern)
    
    if missing_files:
        print("\nWARNING: The following required files are missing:")
        for file in missing_files:
            print(f"- {file}")
        print("\nPlease ensure all required files are present before creating the deployment package.")
        return
    
    print("\nAll required files are present.")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not any(d.endswith(pattern) for pattern in exclude_patterns)]
            
            for file in files:
                file_path = os.path.join(root, file)
                # Skip excluded files
                if any(file.endswith(pattern) for pattern in exclude_patterns):
                    continue
                
                # Check if file is in include patterns
                if any(file_path.startswith(pattern) for pattern in include_patterns):
                    # Get the relative path for the zip file
                    arcname = os.path.relpath(file_path, '.')
                    print(f"Adding: {arcname}")
                    zipf.write(file_path, arcname)
    
    print(f"\nDeployment package created successfully: {zip_filename}")
    print("\nFiles included in the package:")
    with zipfile.ZipFile(zip_filename, 'r') as zipf:
        for file in zipf.namelist():
            print(f"- {file}")

if __name__ == '__main__':
    create_deployment_zip() 