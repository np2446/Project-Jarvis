"""
File transfer utilities for moving data between local machine and GPU instances.
Uses Hyperbolic's SSH access for secure file transfer.
"""

import os
import json
import time
import subprocess
import tempfile
import hashlib
import base64
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from hyperbolic_agentkit_core.actions.ssh_access import connect_ssh
from hyperbolic_agentkit_core.actions.remote_shell import execute_remote_command
from hyperbolic_agentkit_core.actions.ssh_manager import ssh_manager
from hyperbolic_agentkit_core.actions.get_gpu_status import get_gpu_status

class FileTransfer:
    """Handles file transfers between local machine and GPU instances."""
    
    def __init__(self, instance_id: str):
        """Initialize file transfer handler.
        
        Args:
            instance_id: ID of the GPU instance
        """
        self.instance_id = instance_id
        self._ensure_ssh_access()
    
    def _ensure_ssh_access(self) -> None:
        """Ensure SSH access is configured for the instance."""
        # Check if SSH connection is already active
        if ssh_manager.is_connected:
            print("SSH connection is already active. Proceeding...")
            return
            
        # Get SSH key path from environment variable
        ssh_key_path = os.environ.get('SSH_PRIVATE_KEY_PATH')
        if not ssh_key_path:
            raise ValueError("SSH_PRIVATE_KEY_PATH environment variable is required but not set")
        
        ssh_key_path = os.path.expanduser(ssh_key_path)
        if not os.path.exists(ssh_key_path):
            raise FileNotFoundError(f"SSH key file not found at {ssh_key_path}")
            
        # Get SSH key password from environment
        ssh_key_password = os.environ.get('SSH_KEY_PASSWORD')
        
        # Get instance IP and port
        ip_info = self._get_instance_ip()
        if not ip_info:
            raise RuntimeError(f"Could not determine IP address for instance {self.instance_id}")
            
        ip_address, port = ip_info
        
        # Connect to the instance
        print(f"Connecting to instance {self.instance_id} at {ip_address}:{port}...")
        ssh_result = connect_ssh(
            host=ip_address,
            username="ubuntu",  # Default username for Hyperbolic instances
            private_key_path=ssh_key_path,
            port=port,
            key_password=ssh_key_password
        )
        
        if "Successfully connected" not in ssh_result:
            # Try alternative username
            print(f"Connection failed with 'ubuntu' username. Trying 'root'...")
            ssh_result = connect_ssh(
                host=ip_address,
                username="root",
                private_key_path=ssh_key_path,
                port=port,
                key_password=ssh_key_password
            )
            
        if "Successfully connected" not in ssh_result:
            raise RuntimeError(f"Failed to establish SSH connection: {ssh_result}")
            
        print(f"SSH connection established successfully")
    
    def _get_instance_ip(self) -> Optional[Tuple[str, int]]:
        """Get IP address and port for the instance.
        
        Returns:
            Tuple of (ip_address, port) if found, None otherwise
        """
        # Get instance status
        status_data = get_gpu_status()
        if isinstance(status_data, str):
            try:
                status = json.loads(status_data)
            except json.JSONDecodeError:
                print(f"Error parsing status data as JSON")
                return None
        else:
            status = status_data
        
        # Find our instance
        instance = None
        instances = []
        
        # Extract instances from different possible formats
        if 'instances' in status and isinstance(status['instances'], list):
            instances = status['instances']
        elif 'data' in status and isinstance(status['data'], list):
            instances = status['data']
        elif 'data' in status and isinstance(status['data'], dict) and 'instances' in status['data']:
            instances = status['data']['instances']
        
        for inst in instances:
            if inst.get('id') == self.instance_id:
                instance = inst
                break
        
        if not instance:
            print(f"Instance {self.instance_id} not found in status data")
            return None
        
        # Try different ways to extract IP address
        ip_address = None
        port = 22  # Default SSH port
        
        # Check for sshCommand field first (most reliable)
        if 'sshCommand' in instance and instance['sshCommand']:
            ssh_cmd = instance['sshCommand']
            print(f"Found sshCommand: {ssh_cmd}")
            
            # Parse the SSH command (format: "ssh username@hostname -p port")
            import re
            host_match = re.search(r'@([^:\s]+)', ssh_cmd)
            port_match = re.search(r'-p\s+(\d+)', ssh_cmd)
            
            if host_match:
                ip_address = host_match.group(1)
                if port_match:
                    try:
                        port = int(port_match.group(1))
                    except (ValueError, TypeError):
                        print(f"Invalid port in sshCommand: {port_match.group(1)}, using default port 22")
                
                print(f"Extracted from sshCommand - IP: {ip_address}, port: {port}")
                return (ip_address, port)
        
        # Check for IP in 'ip' field
        if 'ip' in instance and instance['ip']:
            ip_address = instance['ip']
            print(f"Found IP in 'ip' field: {ip_address}")
        
        # Check for IP in 'ipAddress' field
        elif 'ipAddress' in instance and instance['ipAddress']:
            ip_address = instance['ipAddress']
            print(f"Found IP in 'ipAddress' field: {ip_address}")
        
        # Check for IP in 'ssh' field
        elif 'ssh' in instance and isinstance(instance['ssh'], dict):
            ssh_info = instance['ssh']
            if 'host' in ssh_info and ssh_info['host']:
                ip_address = ssh_info['host']
                print(f"Found IP in 'ssh.host' field: {ip_address}")
            if 'port' in ssh_info and ssh_info['port']:
                try:
                    port = int(ssh_info['port'])
                    print(f"Found port in 'ssh.port' field: {port}")
                except (ValueError, TypeError):
                    print(f"Invalid port in 'ssh.port' field: {ssh_info['port']}, using default port 22")
        
        # Check for IP in 'network' field
        elif 'network' in instance and isinstance(instance['network'], dict):
            network_info = instance['network']
            if 'ip' in network_info and network_info['ip']:
                ip_address = network_info['ip']
                print(f"Found IP in 'network.ip' field: {ip_address}")
        
        # Check for IP in 'status' field
        elif 'status' in instance and isinstance(instance['status'], dict):
            status_info = instance['status']
            if 'ip' in status_info and status_info['ip']:
                ip_address = status_info['ip']
                print(f"Found IP in 'status.ip' field: {ip_address}")
        
        # Check in nested 'instance' field
        elif 'instance' in instance and isinstance(instance['instance'], dict):
            nested = instance['instance']
            
            # Check for sshCommand in nested instance
            if 'sshCommand' in nested and nested['sshCommand']:
                ssh_cmd = nested['sshCommand']
                print(f"Found sshCommand in nested instance: {ssh_cmd}")
                
                # Parse the SSH command
                import re
                host_match = re.search(r'@([^:\s]+)', ssh_cmd)
                port_match = re.search(r'-p\s+(\d+)', ssh_cmd)
                
                if host_match:
                    ip_address = host_match.group(1)
                    if port_match:
                        try:
                            port = int(port_match.group(1))
                        except (ValueError, TypeError):
                            print(f"Invalid port in nested sshCommand: {port_match.group(1)}, using default port 22")
                    
                    print(f"Extracted from nested sshCommand - IP: {ip_address}, port: {port}")
                    return (ip_address, port)
            
            # Check other fields in nested instance
            for field in ['ip', 'ipAddress', 'hostname', 'address']:
                if field in nested and nested[field]:
                    ip_address = nested[field]
                    print(f"Found IP in nested instance.{field}: {ip_address}")
                    break
        
        if ip_address:
            return (ip_address, port)
        return None
    
    def upload_file(self, local_path: str, remote_path: str, max_retries: int = 3) -> None:
        """Upload a file to the GPU instance with retry logic.
        
        Args:
            local_path: Path to local file
            remote_path: Destination path on GPU instance
            max_retries: Maximum number of retry attempts
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        # Ensure SSH connection is active
        self._ensure_ssh_access()
        
        # Create remote directory if needed
        remote_dir = str(Path(remote_path).parent)
        execute_remote_command(f"mkdir -p {remote_dir}", instance_id=self.instance_id)
        
        # Try curl-based upload first
        try:
            print(f"Attempting to upload file via curl: {local_path} -> {remote_path}")
            self.upload_via_curl(local_path, remote_path, max_retries)
            return
        except Exception as e:
            print(f"Curl-based upload failed: {str(e)}")
            print("Falling back to traditional SCP upload...")
        
        # Traditional SCP upload (as fallback)
        # Get SSH connection info
        ssh_info = self._get_ssh_info()
        
        # Build scp command
        host = ssh_info["host"]
        port = ssh_info.get("port", 22)
        user = ssh_info["username"]
        
        # Get SSH key path
        ssh_key_path = os.environ.get('SSH_PRIVATE_KEY_PATH')
        if not ssh_key_path:
            raise ValueError("SSH_PRIVATE_KEY_PATH environment variable is required but not set")
        
        ssh_key_path = os.path.expanduser(ssh_key_path)
        
        # Use scp to upload file with retries
        for attempt in range(max_retries):
            try:
                # Build the scp command
                cmd = [
                    "scp",
                    "-P", str(port),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "ConnectTimeout=30",
                    "-o", "ServerAliveInterval=30",
                    "-i", ssh_key_path,
                    local_path,
                    f"{user}@{host}:{remote_path}"
                ]
                
                print(f"Uploading file (attempt {attempt+1}/{max_retries}): {local_path} -> {remote_path}")
                
                # Execute scp command
                process = subprocess.run(cmd, capture_output=True, text=True)
                
                if process.returncode == 0:
                    print(f"Successfully uploaded file: {local_path}")
                    
                    # Verify the file exists on the remote server
                    verify_cmd = f"test -f {remote_path} && echo 'exists'"
                    verify_result = execute_remote_command(verify_cmd, instance_id=self.instance_id)
                    
                    if "exists" in verify_result:
                        print(f"Verified file exists on remote server: {remote_path}")
                        return
                    else:
                        print(f"Warning: File upload appeared successful, but file not found on remote server")
                else:
                    print(f"Upload failed (attempt {attempt+1}/{max_retries}): {process.stderr}")
            except Exception as e:
                print(f"Upload error (attempt {attempt+1}/{max_retries}): {str(e)}")
            
            # Wait before retrying
            if attempt < max_retries - 1:
                retry_delay = 5 * (attempt + 1)  # Exponential backoff
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
        
        raise RuntimeError(f"Failed to upload file after {max_retries} attempts: {local_path}")
    
    def upload_via_curl(self, local_path: str, remote_path: str, max_retries: int = 3) -> None:
        """Upload a file to the GPU instance using curl.
        
        This method uploads the file to a temporary file sharing service, then
        uses curl on the remote instance to download it.
        
        Args:
            local_path: Path to local file
            remote_path: Destination path on GPU instance
            max_retries: Maximum number of retry attempts
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        # Get file size
        file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
        print(f"File size: {file_size_mb:.2f} MB")
        
        # Choose upload method based on file size
        # For smaller files (< 25 MB), use transfer.sh
        # For larger files, recommend other services
        
        if file_size_mb < 25:
            # Using transfer.sh service (free, no authentication needed)
            for attempt in range(max_retries):
                try:
                    print(f"Uploading to temporary file service (attempt {attempt+1}/{max_retries})...")
                    
                    # Generate a unique filename to avoid collisions
                    unique_filename = f"{uuid.uuid4().hex}_{os.path.basename(local_path)}"
                    
                    # Upload file to transfer.sh
                    upload_cmd = [
                        "curl", 
                        "--upload-file", 
                        local_path,
                        f"https://transfer.sh/{unique_filename}"
                    ]
                    
                    process = subprocess.run(upload_cmd, capture_output=True, text=True, check=True)
                    download_url = process.stdout.strip()
                    
                    print(f"File uploaded to: {download_url}")
                    
                    # Now use curl on the remote server to download the file
                    print(f"Instructing remote server to download file...")
                    download_cmd = f"curl -s -L '{download_url}' -o '{remote_path}' && echo 'success'"
                    result = execute_remote_command(download_cmd, instance_id=self.instance_id, timeout=300)
                    
                    if "success" in result:
                        # Verify file exists and has content
                        verify_cmd = f"test -s '{remote_path}' && echo 'exists'"
                        verify_result = execute_remote_command(verify_cmd, instance_id=self.instance_id)
                        
                        if "exists" in verify_result:
                            print(f"Successfully transferred file via curl: {local_path} -> {remote_path}")
                            return
                        else:
                            print(f"Warning: File download appeared successful, but file not found or empty")
                    else:
                        print(f"Curl download failed (attempt {attempt+1}/{max_retries}): {result}")
                
                except Exception as e:
                    print(f"Error during transfer.sh upload (attempt {attempt+1}/{max_retries}): {str(e)}")
                
                # Wait before retrying
                if attempt < max_retries - 1:
                    retry_delay = 5 * (attempt + 1)  # Exponential backoff
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
        
        # Alternative for larger files: Use gofile.io which supports up to 2GB free
        elif file_size_mb < 2000:  # Less than 2GB
            for attempt in range(max_retries):
                try:
                    print(f"File is too large for transfer.sh. Using gofile.io (attempt {attempt+1}/{max_retries})...")
                    
                    # Step 1: Get server for upload
                    server_response = subprocess.run(
                        ["curl", "https://api.gofile.io/getServer"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    server_data = json.loads(server_response.stdout)
                    if not server_data.get("status") == "ok":
                        raise RuntimeError("Failed to get gofile.io server")
                    
                    server = server_data["data"]["server"]
                    
                    # Step 2: Upload the file
                    upload_cmd = [
                        "curl", 
                        "-F", 
                        f"file=@{local_path}", 
                        f"https://{server}.gofile.io/uploadFile"
                    ]
                    
                    process = subprocess.run(upload_cmd, capture_output=True, text=True, check=True)
                    upload_result = json.loads(process.stdout)
                    
                    if upload_result.get("status") == "ok":
                        download_url = upload_result["data"]["downloadPage"]
                        file_id = upload_result["data"]["fileId"]
                        direct_link = upload_result["data"]["downloadLink"]
                        
                        print(f"File uploaded to: {download_url}")
                        print(f"Direct download link: {direct_link}")
                        
                        # Now use curl on the remote server to download the file
                        print(f"Instructing remote server to download file...")
                        download_cmd = f"curl -s -L '{direct_link}' -o '{remote_path}' && echo 'success'"
                        result = execute_remote_command(download_cmd, instance_id=self.instance_id, timeout=600)
                        
                        if "success" in result:
                            # Verify file exists and has content
                            verify_cmd = f"test -s '{remote_path}' && echo 'exists'"
                            verify_result = execute_remote_command(verify_cmd, instance_id=self.instance_id)
                            
                            if "exists" in verify_result:
                                print(f"Successfully transferred file via gofile.io: {local_path} -> {remote_path}")
                                return
                            else:
                                print(f"Warning: File download appeared successful, but file not found or empty")
                        else:
                            print(f"Curl download failed (attempt {attempt+1}/{max_retries}): {result}")
                    else:
                        print(f"Failed to upload to gofile.io: {upload_result}")
                
                except Exception as e:
                    print(f"Error during gofile.io upload (attempt {attempt+1}/{max_retries}): {str(e)}")
                
                # Wait before retrying
                if attempt < max_retries - 1:
                    retry_delay = 5 * (attempt + 1)  # Exponential backoff
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
        else:
            # For extremely large files, provide guidance
            print(f"File is very large ({file_size_mb:.2f} MB). Consider these options:")
            print("1. Split the file into smaller parts")
            print("2. Use a cloud storage service (S3, GCS, etc.)")
            print("3. Use a dedicated file transfer service")
            print("\nFalling back to manual file handling...")
            
            # Try to use the remote server to download directly from user-provided URL
            url = input("Enter a public URL where the file can be downloaded from (or press Enter to skip): ")
            if url:
                try:
                    print(f"Instructing remote server to download file from: {url}")
                    download_cmd = f"curl -s -L '{url}' -o '{remote_path}' && echo 'success'"
                    result = execute_remote_command(download_cmd, instance_id=self.instance_id, timeout=1800)
                    
                    if "success" in result:
                        # Verify file exists and has content
                        verify_cmd = f"test -s '{remote_path}' && echo 'exists'"
                        verify_result = execute_remote_command(verify_cmd, instance_id=self.instance_id)
                        
                        if "exists" in verify_result:
                            print(f"Successfully transferred file via user-provided URL: {url} -> {remote_path}")
                            return
                    else:
                        print(f"Curl download failed: {result}")
                except Exception as e:
                    print(f"Error using user-provided URL: {str(e)}")
            
            # If we get here, none of the methods worked
            raise RuntimeError(f"Failed to upload large file. Please use a cloud service and provide a download URL.")
                
        # If we reach this point, all retry attempts failed
        raise RuntimeError(f"Failed to upload file via curl after {max_retries} attempts: {local_path}")
    
    def download_file(self, remote_path: str, local_path: str, max_retries: int = 3) -> None:
        """Download a file from the GPU instance with retry logic.
        
        Args:
            remote_path: Path to file on GPU instance
            local_path: Destination path on local machine
            max_retries: Maximum number of retry attempts
        """
        # Ensure SSH connection is active
        self._ensure_ssh_access()
        
        # Create local directory if needed
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)
        
        # Get SSH connection info
        ssh_info = self._get_ssh_info()
        
        # Build scp command
        host = ssh_info["host"]
        port = ssh_info.get("port", 22)
        user = ssh_info["username"]
        
        # Get SSH key path
        ssh_key_path = os.environ.get('SSH_PRIVATE_KEY_PATH')
        if not ssh_key_path:
            raise ValueError("SSH_PRIVATE_KEY_PATH environment variable is required but not set")
        
        ssh_key_path = os.path.expanduser(ssh_key_path)
        
        # Verify the file exists on the remote server
        verify_cmd = f"test -f {remote_path} && echo 'exists'"
        verify_result = execute_remote_command(verify_cmd, instance_id=self.instance_id)
        
        if "exists" not in verify_result:
            raise FileNotFoundError(f"Remote file not found: {remote_path}")
        
        # Use scp to download file with retries
        for attempt in range(max_retries):
            try:
                # Build the scp command
                cmd = [
                    "scp",
                    "-P", str(port),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "ConnectTimeout=30",
                    "-o", "ServerAliveInterval=30",
                    "-i", ssh_key_path,
                    f"{user}@{host}:{remote_path}",
                    local_path
                ]
                
                print(f"Downloading file (attempt {attempt+1}/{max_retries}): {remote_path} -> {local_path}")
                
                # Execute scp command
                process = subprocess.run(cmd, capture_output=True, text=True)
                
                if process.returncode == 0:
                    print(f"Successfully downloaded file: {remote_path}")
                    
                    # Verify the file exists locally
                    if os.path.exists(local_path):
                        print(f"Verified file exists locally: {local_path}")
                        return
                    else:
                        print(f"Warning: File download appeared successful, but file not found locally")
                else:
                    print(f"Download failed (attempt {attempt+1}/{max_retries}): {process.stderr}")
            except Exception as e:
                print(f"Download error (attempt {attempt+1}/{max_retries}): {str(e)}")
            
            # Wait before retrying
            if attempt < max_retries - 1:
                retry_delay = 5 * (attempt + 1)  # Exponential backoff
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
        
        raise RuntimeError(f"Failed to download file after {max_retries} attempts: {remote_path}")
    
    def upload_directory(self, local_dir: str, remote_dir: str, max_retries: int = 3) -> None:
        """Upload a directory to the GPU instance with retry logic.
        
        Args:
            local_dir: Path to local directory
            remote_dir: Destination path on GPU instance
            max_retries: Maximum number of retry attempts
        """
        if not os.path.isdir(local_dir):
            raise NotADirectoryError(f"Local directory not found: {local_dir}")
        
        # Ensure SSH connection is active
        self._ensure_ssh_access()
        
        # Create remote directory if needed
        execute_remote_command(f"mkdir -p {remote_dir}", instance_id=self.instance_id)
        
        # Create a temporary archive of the directory
        print(f"Creating temporary archive of directory: {local_dir}")
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as temp_file:
            temp_archive = temp_file.name
        
        try:
            # Create a tar archive of the directory
            subprocess.run(
                ["tar", "-czf", temp_archive, "-C", os.path.dirname(local_dir), os.path.basename(local_dir)],
                check=True,
                capture_output=True
            )
            
            # Upload the archive using curl
            remote_archive = f"{remote_dir}/temp_archive.tar.gz"
            print(f"Uploading archive via curl: {temp_archive} -> {remote_archive}")
            
            try:
                # Try curl-based upload first
                self.upload_via_curl(temp_archive, remote_archive, max_retries)
            except Exception as e:
                print(f"Curl-based directory upload failed: {str(e)}")
                print("Falling back to traditional upload_file method...")
                self.upload_file(temp_archive, remote_archive, max_retries)
            
            # Extract the archive on the remote system
            print(f"Extracting archive on remote system: {remote_archive}")
            extract_cmd = f"cd {remote_dir} && tar -xzf temp_archive.tar.gz && rm temp_archive.tar.gz && echo 'success'"
            result = execute_remote_command(extract_cmd, instance_id=self.instance_id, timeout=300)
            
            if "success" not in result:
                raise RuntimeError(f"Failed to extract archive on remote system: {result}")
                
            print(f"Successfully uploaded directory: {local_dir} -> {remote_dir}")
            
        finally:
            # Clean up the temporary archive
            if os.path.exists(temp_archive):
                os.unlink(temp_archive)
    
    def download_directory(self, remote_dir: str, local_dir: str, max_retries: int = 3) -> None:
        """Download a directory from the GPU instance.
        
        Args:
            remote_dir: Path to directory on GPU instance
            local_dir: Destination path on local machine
            max_retries: Maximum number of retry attempts
        """
        # Ensure SSH connection is active
        self._ensure_ssh_access()
        
        # Create local directory
        os.makedirs(local_dir, exist_ok=True)
        
        # List files in remote directory
        cmd = f"find {remote_dir} -type f | sort"
        result = execute_remote_command(cmd, instance_id=self.instance_id)
        
        if result.startswith("Error") or "No such file or directory" in result:
            raise FileNotFoundError(f"Remote directory not found or empty: {remote_dir}")
        
        # Download each file
        for remote_path in result.strip().split('\n'):
            if not remote_path:
                continue
                
            # Calculate relative path from remote_dir
            rel_path = os.path.relpath(remote_path, remote_dir)
            local_path = os.path.join(local_dir, rel_path)
            
            # Create local directory structure
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # Download the file
            self.download_file(remote_path, local_path, max_retries)
    
    def list_remote_files(self, remote_path: str) -> List[str]:
        """List files in a remote directory.
        
        Args:
            remote_path: Path to directory on GPU instance
            
        Returns:
            List of file paths
        """
        # Ensure SSH connection is active
        self._ensure_ssh_access()
        
        # List files in remote directory
        cmd = f"find {remote_path} -type f | sort"
        result = execute_remote_command(cmd, instance_id=self.instance_id)
        
        if result.startswith("Error") or "No such file or directory" in result:
            return []
        
        return [path for path in result.strip().split('\n') if path]
    
    def _get_ssh_info(self) -> dict:
        """Get SSH connection information.
        
        Returns:
            dict: SSH connection info with host, username, and port
        """
        # If ssh_manager is connected, use its connection info
        if ssh_manager.is_connected:
            conn_info = ssh_manager.get_connection_info()
            if conn_info.get("status") == "connected":
                return {
                    "host": conn_info.get("host"),
                    "username": conn_info.get("username"),
                    "port": conn_info.get("port", 22)
                }
        
        # Otherwise, get info from instance data
        ip_info = self._get_instance_ip()
        if not ip_info:
            raise RuntimeError(f"Could not determine IP address for instance {self.instance_id}")
            
        ip_address, port = ip_info
        
        # Try to determine username from ssh_manager
        username = "ubuntu"  # Default username for Hyperbolic instances
        
        return {
            "host": ip_address,
            "username": username,
            "port": port
        } 