# Sudo Setup Guide for DuskMan

## Problem
DuskMan is failing with sudo password prompts:
```
sudo: a terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper
sudo: a password is required
```

## Solutions (Choose One)

### Option 1: Passwordless Sudo (Recommended)

This is the most secure and reliable option for automated scripts.

1. **Find the full paths to your commands:**
   ```bash
   which ruskquery
   which rusk-wallet
   ```
   Example output:
   ```
   /usr/local/bin/ruskquery
   /usr/local/bin/rusk-wallet
   ```

2. **Edit the sudoers file:**
   ```bash
   sudo visudo
   ```

3. **Add a line for your user (replace `username` with your actual username):**
   ```
   username ALL=(ALL) NOPASSWD: /usr/local/bin/ruskquery, /usr/local/bin/rusk-wallet
   ```

4. **Update your config.yaml:**
   ```yaml
   SUDO_CONFIG:
     passwordless_sudo: True
     use_stdin_password: False
   ```

### Option 2: Provide Sudo Password via Environment Variable

1. **Set your sudo password in the .env file:**
   ```bash
   echo "SUDO_PASSWORD=your_sudo_password_here" >> .env
   ```

2. **Update your config.yaml:**
   ```yaml
   SUDO_CONFIG:
     passwordless_sudo: False
     use_stdin_password: True
   ```

### Option 3: Disable Sudo (If Not Required)

If you don't actually need sudo for your rusk commands:

1. **Test if commands work without sudo:**
   ```bash
   ruskquery block-height
   rusk-wallet --password "your_password" profiles
   ```

2. **If they work, update config.yaml:**
   ```yaml
   GENERAL:
     use_sudo: False
   ```

## Quick Fix for Current Issue

To immediately fix the current problem, try this:

1. **Check if you actually need sudo:**
   ```bash
   ruskquery block-height
   ```

2. **If it works without sudo, temporarily disable it:**
   ```bash
   # Edit config.yaml and change:
   use_sudo: False
   ```

3. **Restart DuskMan**

## Verification

After implementing any solution, verify it works:

```bash
# Test the commands that were failing:
sudo ruskquery block-height
sudo rusk-wallet --password "your_password" profiles
```

## Security Notes

- **Option 1 (Passwordless sudo)** is most secure as it only allows specific commands
- **Option 2 (Password in .env)** is less secure but functional
- **Option 3 (No sudo)** is most secure if sudo isn't actually needed

## Troubleshooting

### If passwordless sudo doesn't work:
1. Check the paths are correct: `which ruskquery rusk-wallet`
2. Verify the sudoers syntax: `sudo visudo -c`
3. Make sure you're using your exact username: `whoami`

### If environment variable doesn't work:
1. Check the .env file exists and has the right content: `cat .env`
2. Verify the variable is set: `echo $SUDO_PASSWORD`
3. Make sure there are no extra spaces or quotes

### If disabling sudo doesn't work:
1. Check if the commands require special permissions
2. Verify the rusk binaries are in your PATH: `echo $PATH`
3. Check file permissions: `ls -la $(which ruskquery rusk-wallet)` 