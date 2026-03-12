from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0067_alter_userbillingprofile_options"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE user_accounts_salespipeline
                ADD COLUMN IF NOT EXISTS stripe_customer_id varchar(128) NOT NULL DEFAULT '';

                ALTER TABLE user_accounts_salespipeline
                ADD COLUMN IF NOT EXISTS stripe_subscription_id varchar(128) NOT NULL DEFAULT '';

                ALTER TABLE user_accounts_salespipeline
                ADD COLUMN IF NOT EXISTS stripe_subscription_item_id varchar(128) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE user_accounts_salespipeline
                DROP COLUMN IF EXISTS stripe_subscription_item_id;

                ALTER TABLE user_accounts_salespipeline
                DROP COLUMN IF EXISTS stripe_subscription_id;

                ALTER TABLE user_accounts_salespipeline
                DROP COLUMN IF EXISTS stripe_customer_id;
            """,
        ),
    ]