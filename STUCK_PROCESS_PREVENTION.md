# Stuck Process Prevention System

## Overview

This document describes the comprehensive stuck process prevention system implemented to prevent the DuskMan application from hanging due to stuck `rusk-wallet` or other blockchain commands.

## Problem Solved

The original issue was that a `rusk-wallet stake-info` command got stuck for almost 10 hours, causing:
- The stake management loop to hang completely
- The timer display to show "Processing..." indefinitely
- No recovery mechanism to detect or kill the stuck process

## Solution Components

### 1. Process Watchdog (`utilities/process_watchdog.py`)

A dedicated process monitoring system that:
- **Monitors all spawned processes** with configurable timeouts
- **Automatically kills stuck processes** and their children
- **Provides detailed logging** of process lifecycle events
- **Supports different timeout values** for different command types
- **Runs as a background task** alongside the main application

**Key Features:**
- Wallet commands: 120-second default timeout
- General commands: 300-second default timeout  
- Recursive process tree killing (kills child processes too)
- Graceful shutdown with SIGTERM, followed by SIGKILL if needed
- Real-time monitoring every 10 seconds

### 2. Enhanced Blockchain Client (`utilities/blockchain_client.py`)

**Robust Command Execution:**
- **Retry mechanism** with exponential backoff (3 retries by default)
- **Multiple timeout strategies** based on command criticality
- **Process group management** to ensure complete cleanup
- **Enhanced error handling** with detailed logging

**Timeout Hierarchy:**
- Simple queries (block height, peers): 30 seconds
- Wallet commands: 90 seconds  
- Critical operations (stake-info, staking): 120 seconds

**Retry Strategy:**
- Exponential backoff: 5s, 10s, 15s delays between retries
- Different retry counts for different operation types
- Comprehensive error logging for debugging

### 3. Configuration System

**New Configuration Section (`PROCESS_WATCHDOG`):**
```yaml
PROCESS_WATCHDOG:
  wallet_command_timeout: 120    # Timeout for wallet commands
  general_command_timeout: 300   # Timeout for general commands  
  max_retries: 3                 # Maximum retry attempts
  retry_delay: 5                 # Base delay between retries
```

### 4. Graceful Shutdown Handling

**Application Lifecycle Management:**
- Proper watchdog startup during application initialization
- Graceful shutdown on CTRL-C or errors
- Cleanup of all monitored processes on exit
- Prevention of orphaned processes

## Implementation Details

### Process Registration Flow

1. **Command Execution Initiated**
   ```python
   process = await asyncio.create_subprocess_shell(command, ...)
   ```

2. **Process Registered with Watchdog**
   ```python
   watchdog.register_process(process.pid, command, start_time)
   ```

3. **Monitoring Begins**
   - Watchdog checks process status every 10 seconds
   - Tracks elapsed time against configured timeout

4. **Timeout Handling**
   - Process killed if timeout exceeded
   - Children processes killed recursively
   - Process unregistered from monitoring

5. **Normal Completion**
   ```python
   watchdog.unregister_process(process.pid)
   ```

### Error Recovery Strategies

**Level 1: Command Timeout**
- Individual command times out (30-120s)
- Process killed and cleaned up
- Error logged and retry attempted

**Level 2: Retry Mechanism**  
- Failed commands retried up to 3 times
- Exponential backoff between attempts
- Different retry counts for critical vs. non-critical operations

**Level 3: Watchdog Intervention**
- Backup timeout monitoring (120-300s)
- Kills processes that bypass normal timeout handling
- Handles edge cases where asyncio timeout fails

**Level 4: Circuit Breaker**
- Multiple consecutive failures trigger recovery mode
- Extended timeouts and reduced operation frequency
- Prevents cascade failures

## Configuration Examples

### Conservative Settings (Slower but More Reliable)
```yaml
PROCESS_WATCHDOG:
  wallet_command_timeout: 180    # 3 minutes
  general_command_timeout: 600   # 10 minutes
  max_retries: 5                 # More retries
  retry_delay: 10                # Longer delays
```

### Aggressive Settings (Faster but Less Tolerant)
```yaml
PROCESS_WATCHDOG:
  wallet_command_timeout: 60     # 1 minute
  general_command_timeout: 120   # 2 minutes
  max_retries: 2                 # Fewer retries
  retry_delay: 3                 # Shorter delays
```

## Monitoring and Debugging

### Log Messages to Watch For

**Normal Operation:**
```
[INFO] Process Watchdog: Starting process monitoring
[DEBUG] Process Watchdog: Registered PID 12345: rusk-wallet stake-info...
[DEBUG] Process Watchdog: Unregistered PID 12345: rusk-wallet stake-info...
```

**Stuck Process Detection:**
```
[WARNING] Process Watchdog: Killing stuck process PID 12345 after 120.0s: rusk-wallet stake-info...
[INFO] Process Watchdog: Successfully killed stuck process PID 12345
```

**Retry Attempts:**
```
[WARNING] Command Retry: Attempt 2/4 for: rusk-wallet stake-info...
[INFO] Command Retry Success: Command succeeded on attempt 2
```

### Watchdog Status Monitoring

The watchdog provides real-time status information:
```python
status = watchdog.get_status()
# Returns:
# {
#   'running': True,
#   'monitored_count': 2,
#   'active_processes': [
#     {'pid': 12345, 'command': 'rusk-wallet...', 'elapsed': 45.2, 'timeout': 120}
#   ]
# }
```

## Benefits

1. **Prevents Application Hangs**: No more indefinite "Processing..." states
2. **Automatic Recovery**: Stuck processes are detected and killed automatically  
3. **Improved Reliability**: Multiple layers of timeout and retry protection
4. **Better Debugging**: Comprehensive logging of all process lifecycle events
5. **Configurable Behavior**: Timeouts and retry behavior can be tuned per environment
6. **Resource Protection**: Prevents accumulation of zombie processes
7. **Graceful Degradation**: Application continues operating even with occasional command failures

## Dependencies

- **psutil**: For advanced process management and monitoring
- **asyncio**: For concurrent process execution and monitoring
- **signal**: For process termination handling

## Testing

The system has been tested with:
- Simulated stuck processes (verified 10-second timeout kills process)
- Normal command execution (verified no interference)
- Graceful shutdown scenarios (verified proper cleanup)
- Multiple concurrent processes (verified independent monitoring)

## Future Enhancements

Potential improvements for future versions:
- **Adaptive timeouts** based on historical command performance
- **Health metrics** and alerting for excessive timeout rates
- **Process resource monitoring** (CPU, memory usage)
- **Integration with external monitoring systems**
- **Command performance analytics** and optimization suggestions 