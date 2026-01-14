// Sample application with common bug patterns

class UserManager {
    constructor() {
        this.users = [];
    }

    // BUG: No validation for duplicate usernames
    addUser(username, email) {
        const user = {
            username: username,
            email: email,
            createdAt: new Date()
        };
        this.users.push(user);
        return user;
    }

    // BUG: Case-sensitive comparison and potential null reference
    findUser(username) {
        for (let i = 0; i < this.users.length; i++) {
            if (this.users[i].username == username) {  // FIXME: Using == instead of ===
                return this.users[i];
            }
        }
        return null;
    }

    // BUG: Array modification during iteration
    deleteInactiveUsers(inactiveDays) {
        const now = new Date();
        for (let i = 0; i < this.users.length; i++) {
            const daysSinceCreation = (now - this.users[i].createdAt) / (1000 * 60 * 60 * 24);
            if (daysSinceCreation > inactiveDays) {
                this.users.splice(i, 1);  // BUG: Modifying array during iteration
            }
        }
    }

    // TODO: Add email validation
    updateUserEmail(username, newEmail) {
        const user = this.findUser(username);
        if (!user) {
            throw new Error(`User '${username}' not found`);
        }
        user.email = newEmail;
        return user;
    }

    // BUG: Memory leak - circular reference
    getUserWithManager(username) {
        const user = this.findUser(username);
        if (user) {
            user.manager = this;  // Creates circular reference
        }
        return user;
    }
}

// Example usage
const manager = new UserManager();
manager.addUser("john", "john@example.com");
manager.addUser("jane", "jane@example.com");

console.log(manager.findUser("John"));  // Returns null due to case sensitivity
console.log(manager.updateUserEmail("bob", "bob@new.com"));  // Will crash
