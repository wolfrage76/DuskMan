import asyncio
import psutil
import signal
import time
from typing import Dict, Set, Optional, Callable
from datetime import datetime, timedelta

class ProcessWatchdog:
    """
    Monitors processes and kills them if they exceed timeout limits.
    Specifically designed to prevent stuck rusk-wallet commands.
    """
    
    def __init__(self, log_action_func: Optional[Callable] = None):
        """
        Initialize the process watchdog.
        
        Args:
            log_action_func: Function to call for logging
        """
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        self.monitored_processes: Dict[int, Dict] = {}
        self.max_command_timeout = 300  # 5 minutes max for any command
        self.wallet_command_timeout = 120  # 2 minutes max for wallet commands
        self.running = False
        self._shutdown_event = asyncio.Event()
        
    async def start(self):
        """Start the watchdog monitoring loop."""
        if self.running:
            return
            
        self.running = True
        self._shutdown_event.clear()
        self.log_action("Process Watchdog", "Starting process monitoring", "info")
        
        # Start the monitoring loop as a background task
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
    async def stop(self):
        """Stop the watchdog monitoring."""
        self.running = False
        self._shutdown_event.set()
        self.log_action("Process Watchdog", "Stopping process monitoring", "info")
        
        # Wait for the monitor task to complete
        if hasattr(self, '_monitor_task') and not self._monitor_task.done():
            try:
                await asyncio.wait_for(self._monitor_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
        
    def register_process(self, pid: int, command: str, start_time: Optional[datetime] = None):
        """
        Register a process for monitoring.
        
        Args:
            pid: Process ID to monitor
            command: Command being executed
            start_time: When the process started (defaults to now)
        """
        if start_time is None:
            start_time = datetime.now()
            
        # Determine timeout based on command type
        timeout = self.wallet_command_timeout if 'rusk-wallet' in command else self.max_command_timeout
        
        self.monitored_processes[pid] = {
            'command': command,
            'start_time': start_time,
            'timeout': timeout,
            'killed': False
        }
        
        self.log_action("Process Watchdog", f"Registered PID {pid}: {command[:50]}...", "debug")
        
    def unregister_process(self, pid: int):
        """
        Unregister a process from monitoring.
        
        Args:
            pid: Process ID to unregister
        """
        if pid in self.monitored_processes:
            command = self.monitored_processes[pid]['command']
            del self.monitored_processes[pid]
            self.log_action("Process Watchdog", f"Unregistered PID {pid}: {command[:50]}...", "debug")
            
    async def _monitor_loop(self):
        """Main monitoring loop that checks for stuck processes."""
        while self.running and not self._shutdown_event.is_set():
            try:
                current_time = datetime.now()
                stuck_processes = []
                
                for pid, info in self.monitored_processes.items():
                    if info['killed']:
                        continue
                        
                    elapsed = current_time - info['start_time']
                    if elapsed.total_seconds() > info['timeout']:
                        stuck_processes.append((pid, info))
                        
                # Kill stuck processes
                for pid, info in stuck_processes:
                    await self._kill_stuck_process(pid, info)
                    
                # Clean up completed processes
                await self._cleanup_completed_processes()
                
                # Wait before next check
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                self.log_action("Process Watchdog", f"Error in monitor loop: {str(e)}", "error")
                await asyncio.sleep(30)  # Wait longer on error
                
    async def _kill_stuck_process(self, pid: int, info: Dict):
        """
        Kill a stuck process and its children.
        
        Args:
            pid: Process ID to kill
            info: Process information dictionary
        """
        try:
            elapsed = datetime.now() - info['start_time']
            command = info['command']
            
            self.log_action(
                "Process Watchdog", 
                f"Killing stuck process PID {pid} after {elapsed.total_seconds():.1f}s: {command[:100]}...",
                "warning"
            )
            
            # Try to get the process and its children
            try:
                process = psutil.Process(pid)
                children = process.children(recursive=True)
                
                # Kill children first
                for child in children:
                    try:
                        self.log_action("Process Watchdog", f"Killing child process PID {child.pid}", "debug")
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                        
                # Kill the main process
                process.kill()
                
                # Wait for process to die
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    # Force kill if it doesn't die gracefully
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
                        
            except psutil.NoSuchProcess:
                # Process already died
                pass
            except psutil.AccessDenied:
                # Try using system kill as fallback
                try:
                    import os
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                    
            # Mark as killed
            info['killed'] = True
            
            self.log_action(
                "Process Watchdog", 
                f"Successfully killed stuck process PID {pid}",
                "info"
            )
            
        except Exception as e:
            self.log_action(
                "Process Watchdog", 
                f"Error killing process PID {pid}: {str(e)}",
                "error"
            )
            
    async def _cleanup_completed_processes(self):
        """Remove completed or killed processes from monitoring."""
        completed_pids = []
        
        for pid, info in self.monitored_processes.items():
            try:
                # Check if process still exists
                process = psutil.Process(pid)
                if not process.is_running() or info['killed']:
                    completed_pids.append(pid)
            except psutil.NoSuchProcess:
                completed_pids.append(pid)
                
        # Remove completed processes
        for pid in completed_pids:
            if pid in self.monitored_processes:
                del self.monitored_processes[pid]
                
    def get_monitored_count(self) -> int:
        """Get the number of currently monitored processes."""
        return len([p for p in self.monitored_processes.values() if not p['killed']])
        
    def get_status(self) -> Dict:
        """Get current watchdog status."""
        active_processes = [
            {
                'pid': pid,
                'command': info['command'][:50] + '...' if len(info['command']) > 50 else info['command'],
                'elapsed': (datetime.now() - info['start_time']).total_seconds(),
                'timeout': info['timeout']
            }
            for pid, info in self.monitored_processes.items()
            if not info['killed']
        ]
        
        return {
            'running': self.running,
            'monitored_count': len(active_processes),
            'active_processes': active_processes
        } 