# Task: Laravel Filament Admin Panel for AI Interview Trainer

## Overview
Build an admin panel using Laravel + Filament for the AI Interview Trainer project. The panel manages users, tariff plans, subscriptions, payments, and displays statistics. Only users with roles **Admin** or **Manager** can access the panel.

## Architecture

```
ai-interview-trainer/
├── bot/                     # Existing Python Telegram bot (unchanged)
├── db/                      # Existing Python DB models
├── ai/                      # Existing AI integration
├── admin/                   # NEW: Laravel application
│   ├── app/
│   ├── database/migrations/
│   └── ...
├── data/interviews.db       # Shared SQLite database (Phase 1)
└── CLAUDE.md
```

**Phase 1**: Laravel app reads/writes the shared SQLite database.
**Phase 2** (later): Migrate to PostgreSQL for both apps.

**Important**: Laravel and the Python bot share the same database. Laravel migrations MUST NOT break existing Python bot tables (`users`, `sessions`, `answers`).

---

## Database Schema (NEW tables to add)

### 1. `tariff_plans` — Subscription plans
```php
Schema::create('tariff_plans', function (Blueprint $table) {
    $table->id();
    $table->string('name');                    // e.g. "Free", "Pro", "Enterprise"
    $table->decimal('price', 10, 2);           // Monthly price in USD
    $table->integer('duration_days');           // 30, 90, 365
    $table->json('features')->nullable();       // ["unlimited_interviews", "detailed_feedback", ...]
    $table->integer('max_interviews_per_day')->default(2);
    $table->boolean('is_active')->default(true);
    $table->timestamps();
});
```

### 2. `subscriptions` — User subscriptions
```php
Schema::create('subscriptions', function (Blueprint $table) {
    $table->id();
    $table->foreignId('user_id')->constrained('users', 'id');  // references users.id
    $table->foreignId('tariff_plan_id')->constrained('tariff_plans');
    $table->dateTime('start_date');
    $table->dateTime('end_date');
    $table->enum('status', ['active', 'expired', 'cancelled', 'trial'])->default('active');
    $table->timestamps();
});
```

### 3. `payments` — Payment records
```php
Schema::create('payments', function (Blueprint $table) {
    $table->id();
    $table->foreignId('user_id')->constrained('users', 'id');
    $table->foreignId('tariff_plan_id')->nullable()->constrained('tariff_plans');
    $table->foreignId('subscription_id')->nullable()->constrained('subscriptions');
    $table->decimal('amount', 10, 2);
    $table->string('currency', 3)->default('USD');
    $table->enum('status', ['pending', 'completed', 'failed', 'refunded'])->default('pending');
    $table->string('payment_method')->nullable();  // stripe, crypto, etc.
    $table->string('payment_id')->nullable();       // external payment gateway ID
    $table->dateTime('paid_at')->nullable();
    $table->timestamps();
});
```

### 4. Extend existing `users` table (Python bot)
Add these columns to the existing `users` table (Python bot model). **Do NOT create a new users table** — alter the existing one:
```php
Schema::table('users', function (Blueprint $table) {
    $table->string('role')->default('user');       // admin, manager, user
    $table->string('email')->nullable()->unique();
    $table->string('password')->nullable();          // Laravel auth
    $table->string('phone')->nullable();
    $table->rememberToken();
    $table->timestamp('email_verified_at')->nullable();
});
```

---

## Filament Resources

### 1. UserResource
- List all users with columns: Telegram ID, Username, Email, Role, Tariff Plan, Created At
- Filters: by role (admin/manager/user), by tariff plan, by date range
- Actions: Edit user (assign role, assign tariff plan), View subscriptions
- View page: shows user info + subscription history + payment history

### 2. TariffPlanResource
- CRUD for tariff plans
- Columns: Name, Price, Duration, Interviews/day, Active
- Form fields: name, price, duration_days, features (repeater/key-value), max_interviews_per_day, is_active (toggle)
- Validation: price > 0, duration_days > 0

### 3. SubscriptionResource
- List with columns: User, Tariff Plan, Start Date, End Date, Status
- Filters: by status (active/expired/cancelled), by tariff plan
- Widget on dashboard: count of active subscriptions

### 4. PaymentResource
- List with columns: User, Amount, Currency, Status, Payment Method, Paid At
- Filters: by status, by date range, by tariff plan
- Actions: View receipt details
- Export: CSV export of filtered payments

---

## Dashboard Statistics

Filament dashboard widgets:

### Stats Overview (cards/panels)
1. **Total Users** — count of all registered users
2. **Active Subscriptions** — count of subscriptions with status=active
3. **Monthly Revenue (MRR)** — sum of completed payments this month
4. **Total Revenue** — all-time completed payments sum

### Charts
1. **Revenue Over Time** — line chart, last 30 days, daily revenue
2. **New Users Over Time** — line chart, last 30 days, new registrations
3. **Payment Status Distribution** — pie chart (completed vs failed vs pending)
4. **Subscriptions by Tariff** — bar chart, active subscriptions per plan
5. **Users by Role** — pie chart (admin vs manager vs user)

---

## Roles & Permissions (spatie/laravel-permission)

Use **spatie/laravel-permission** for role & permission management.

### Roles
- **admin** — full access to all resources (CRUD)
- **manager** — view-only access to resources
- **user** — no panel access

### Permissions (seeded)
```php
// User permissions
'view_users', 'create_users', 'edit_users', 'delete_users'

// Tariff plan permissions
'view_tariffs', 'create_tariffs', 'edit_tariffs', 'delete_tariffs'

// Subscription permissions
'view_subscriptions', 'create_subscriptions', 'edit_subscriptions', 'delete_subscriptions'

// Payment permissions
'view_payments', 'edit_payments'

// Dashboard permissions
'view_dashboard'
```

### Role-Permission Mapping

| Permission         | admin | manager |
|--------------------|-------|---------|
| view_dashboard     | ✅    | ✅      |
| view_users         | ✅    | ✅      |
| create_users       | ✅    | ❌      |
| edit_users         | ✅    | ❌      |
| delete_users       | ✅    | ❌      |
| view_tariffs       | ✅    | ✅      |
| create_tariffs     | ✅    | ❌      |
| edit_tariffs       | ✅    | ❌      |
| delete_tariffs     | ✅    | ❌      |
| view_subscriptions | ✅    | ✅      |
| create/edit/delete | ✅    | ❌      |
| view_payments      | ✅    | ✅      |
| edit_payments      | ✅    | ❌      |
| export_payments    | ✅    | ✅      |

### Integration
- Install: `composer require spatie/laravel-permission`
- Install Filament Shield: `composer require bezhansalleh/filament-shield`
- Publish migration: `php artisan vendor:publish --provider="Spatie\Permission\PermissionServiceProvider"`
- Generate Shield resources: `php artisan shield:install`
- Use `HasRoles` trait in User model
- Filament resources use `->authorize()` with `@can` or `$this->can()`

---

## Technical Requirements

### Stack
- **Laravel 12** (latest stable)
- **Filament 5.x** (Panel Builder)
- **spatie/laravel-permission** for roles & permissions
- **bezhanSalleh/filament-shield** for Filament integration
- **SQLite** (Phase 1, same file as Python bot: `data/interviews.db`)
- **Filament's built-in auth** for admin login
- **Tailwind CSS** (included with Filament)

### Key Config
- Database: `sqlite` at `../data/interviews.db` (relative to admin/)
- Session: `file` driver (or `database`)
- Mail: `log` driver initially
- Queue: `sync` driver initially

### Code Standards
- PHP 8.2+ strict types
- Type hints on all methods
- PSR-4 autoloading
- PSR-12 coding style
- Use Laravel Pint or PHP CS Fixer
- All queries with Eloquent (no raw SQL except migrations)
- Filament Policies for authorization

---

## Project Structure (admin/)

```
admin/
├── app/
│   ├── Filament/
│   │   ├── Resources/
│   │   │   ├── UserResource.php
│   │   │   ├── TariffPlanResource.php
│   │   │   ├── SubscriptionResource.php
│   │   │   └── PaymentResource.php
│   │   └── Widgets/
│   │       ├── StatsOverview.php
│   │       ├── RevenueChart.php
│   │       ├── NewUsersChart.php
│   │       ├── PaymentStatusChart.php
│   │       └── SubscriptionsByTariffChart.php
│   ├── Models/
│   │   ├── User.php          (extends Authenticatable, HasRoles)
│   │   ├── TariffPlan.php
│   │   ├── Subscription.php
│   │   └── Payment.php
│   └── Providers/
├── database/
│   ├── migrations/
│   │   ├── xxxx_add_role_to_users_table.php
│   │   ├── xxxx_create_tariff_plans_table.php
│   │   ├── xxxx_create_subscriptions_table.php
│   │   └── xxxx_create_payments_table.php
│   └── seeders/
│       ├── RoleAndPermissionSeeder.php
│       └── DatabaseSeeder.php
├── resources/
├── routes/
├── composer.json
└── .env.example
```

---

## Steps (for Claude Code to execute)

1. Create `admin/` directory in project root
2. Run `composer create-project laravel/laravel .` inside `admin/`
3. Install Filament: `composer require filament/filament`
4. Install spatie/laravel-permission: `composer require spatie/laravel-permission`
5. Install Filament Shield: `composer require bezhansalleh/filament-shield`
6. Publish & migrate spatie tables: `php artisan vendor:publish --provider="Spatie\Permission\PermissionServiceProvider"` + `php artisan migrate`
7. Configure SQLite database connection (point to `../data/interviews.db`)
8. Create Models: User (with HasRoles trait), TariffPlan, Subscription, Payment
9. Create migrations for new tables + alter users table
10. Run migrations
11. Set up Filament panel with Shield: `php artisan shield:install`
12. Create Filament Resources: UserResource, TariffPlanResource, SubscriptionResource, PaymentResource
13. Create Dashboard widgets with charts (StatsOverview, RevenueChart, NewUsersChart, etc.)
14. Create a seeder with: default tariff plans (Free, Pro, Enterprise), roles (admin, manager), permissions, admin user
15. Verify: `php artisan serve` + check Filament panel at `/admin`

## Seeding Default Data

```php
// RoleAndPermissionSeeder.php

use Spatie\Permission\Models\Role;
use Spatie\Permission\Models\Permission;

// Create permissions
$permissions = [
    'view_users', 'create_users', 'edit_users', 'delete_users',
    'view_tariffs', 'create_tariffs', 'edit_tariffs', 'delete_tariffs',
    'view_subscriptions', 'create_subscriptions', 'edit_subscriptions', 'delete_subscriptions',
    'view_payments', 'edit_payments',
    'view_dashboard',
];

foreach ($permissions as $permission) {
    Permission::create(['name' => $permission]);
}

// Create roles and assign permissions
$admin = Role::create(['name' => 'admin']);
$admin->givePermissionTo(Permission::all());

$manager = Role::create(['name' => 'manager']);
$manager->givePermissionTo([
    'view_dashboard',
    'view_users',
    'view_tariffs',
    'view_subscriptions',
    'view_payments',
    'export_payments',
]);

// DatabaseSeeder.php

// Default Tariff Plans
TariffPlan::create(['name' => 'Free', 'price' => 0, 'duration_days' => 9999, 'max_interviews_per_day' => 2, 'features' => ['basic_interviews', 'text_feedback']]);
TariffPlan::create(['name' => 'Pro', 'price' => 19.99, 'duration_days' => 30, 'max_interviews_per_day' => 10, 'features' => ['unlimited_interviews', 'detailed_feedback', 'system_design', 'behavioral']]);
TariffPlan::create(['name' => 'Enterprise', 'price' => 49.99, 'duration_days' => 30, 'max_interviews_per_day' => 50, 'features' => ['everything_in_pro', 'priority_support', 'custom_questions', 'team_access']]);

// Default Admin user
$admin = User::create([
    'telegram_id' => 0,
    'username' => 'admin',
    'email' => 'admin@interviewai.app',
    'password' => Hash::make('admin123'),
    'first_name' => 'Admin',
]);
$admin->assignRole('admin');

// Default Manager user (for testing)
$manager = User::create([
    'telegram_id' => 1,
    'username' => 'manager',
    'email' => 'manager@interviewai.app',
    'password' => Hash::make('manager123'),
    'first_name' => 'Manager',
]);
$manager->assignRole('manager');
```

---

## Verification Checklist
- [ ] `php artisan migrate` runs without errors
- [ ] `php artisan db:seed` creates roles, permissions, default plans + admin/manager users
- [ ] `php artisan serve` starts without errors
- [ ] Filament panel loads at `/admin`
- [ ] Login with admin@interviewai.app / admin123 works with full access
- [ ] Login with manager@interviewai.app / manager123 works with view-only access
- [ ] Dashboard shows stats widgets + charts
- [ ] UserResource shows all users from the shared DB
- [ ] Manager user CANNOT edit/delete resources
- [ ] spatie/laravel-permission tables created: `roles`, `permissions`, `model_has_roles`, `model_has_permissions`, `role_has_permissions`
- [ ] Python bot still works (no breaking changes)
